"""Resumable, transactionally checkpointed full-result export."""
from __future__ import annotations
import csv
import hashlib
import json
import sqlite3
from .core import Error, now, digest, work_id
from .api import Client, abstract

COLUMNS = ['id', 'doi', 'title', 'authors', 'year', 'date', 'type', 'source', 'volume', 'issue',
           'first_page', 'last_page', 'abstract', 'url', 'language', 'is_xpac']

def record_row(record):
    location = record.get('primary_location') or {}
    source = location.get('source') or {}
    biblio = record.get('biblio') or {}
    return dict(zip(COLUMNS, [work_id(record['id']), record.get('doi') or '', record.get('display_name') or '',
        '; '.join((a.get('author') or {}).get('display_name', '') for a in record.get('authorships') or []),
        record.get('publication_year') or '', record.get('publication_date') or '', record.get('type') or '',
        source.get('display_name') or '', biblio.get('volume') or '', biblio.get('issue') or '',
        biblio.get('first_page') or '', biblio.get('last_page') or '', abstract(record),
        location.get('landing_page_url') or record.get('doi') or record['id'],
        record.get('language') or '', record.get('is_xpac', '')]))

def ris_line(tag, value):
    return tag + '  - ' + ' '.join(str(value).splitlines()) + '\n'

def csv_cell(value):
    # Prevent spreadsheet formulas while preserving original strings in JSONL and RIS.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value

def render_exports(db, folder, complete):
    prefix = 'results' if complete else 'results.partial'
    csv_path, ris_path, json_path = [folder / (prefix + ext) for ext in ('.csv', '.ris', '.jsonl')]
    with csv_path.open('w', newline='', encoding='utf-8') as cf, ris_path.open('w', encoding='utf-8') as rf, json_path.open('w', encoding='utf-8') as jf:
        writer = csv.DictWriter(cf, fieldnames=COLUMNS); writer.writeheader()
        for (raw,) in db.execute('select body from records order by id'):
            record = json.loads(raw); row = record_row(record)
            writer.writerow({k: csv_cell(v) for k, v in row.items()})
            jf.write(raw + '\n')
            kind = {'article': 'JOUR', 'review': 'JOUR', 'book': 'BOOK', 'book-chapter': 'CHAP',
                    'dissertation': 'THES', 'dataset': 'DATA', 'preprint': 'UNPB'}.get(row['type'], 'GEN')
            rf.write(ris_line('TY', kind))
            for tag, key in [('ID', 'id'), ('TI', 'title'), ('PY', 'year'), ('DA', 'date'), ('JO', 'source'),
                             ('VL', 'volume'), ('IS', 'issue'), ('SP', 'first_page'), ('EP', 'last_page'),
                             ('AB', 'abstract'), ('UR', 'url'), ('LA', 'language')]:
                if row[key] != '':
                    rf.write(ris_line(tag, row[key]))
            if row['doi']:
                rf.write(ris_line('DO', row['doi'].removeprefix('https://doi.org/')))
            for author in record.get('authorships') or []:
                name = (author.get('author') or {}).get('display_name')
                if name:
                    rf.write(ris_line('AU', name))
            rf.write('ER  - \n\n')
    def sha(path):
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    return {p.name: sha(p) for p in (csv_path, ris_path, json_path)}

def export(ws, client=None):
    ws.require_online()
    validated = ws.get('validation-manifest.json', {})
    if not validated.get('ok') or validated.get('input_sha256') != ws.fingerprint():
        raise Error('A current validated report is required before exporting')
    for name, sha in validated['files'].items():
        path = ws.root / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Error('Validated delivery artifact was modified: ' + name)
    client = client or Client(ws)
    query = validated['oqo']
    key = digest(query)
    folder = ws.root / 'exports' / key
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'checkpoint.sqlite3')
    db.execute('create table if not exists records (id text primary key, body text not null)')
    db.execute('create table if not exists state (key text primary key, value text not null)')
    state_row = db.execute("select value from state where key='checkpoint'").fetchone()
    state = json.loads(state_row[0]) if state_row else {'query_sha256': key, 'started_at': now(), 'cursor': '*',
                    'complete': False, 'pages': 0, 'received': 0, 'counts': [], 'seen_cursors': []}
    error = None
    try:
        while not state['complete']:
            cursor = state['cursor']
            data = client.search(query, cursor=cursor, per_page=100)
            rows, meta = data['results'], data['meta']
            if 'next_cursor' not in meta:
                raise Error('Cursor response lacks next_cursor; completion cannot be established')
            next_cursor = meta['next_cursor']
            if next_cursor and (next_cursor == cursor or next_cursor in state['seen_cursors']):
                raise Error('Repeated cursor; export stopped to prevent an infinite loop')
            if not rows and next_cursor:
                raise Error('Empty page with a continuation cursor; export remains incomplete')
            next_state = {**state, 'pages': state['pages'] + 1,
                'received': state['received'] + len(rows), 'cursor': next_cursor,
                'complete': next_cursor is None, 'counts': sorted(set([*state['counts'], meta['count']])),
                'seen_cursors': [*state['seen_cursors'], cursor]}
            with db:
                for r in rows:
                    db.execute('insert or replace into records values (?, ?)',
                               (work_id(r['id']), json.dumps(r, ensure_ascii=False)))
                db.execute("insert or replace into state values ('checkpoint', ?)", (json.dumps(next_state),))
            state = next_state
    except (Error, KeyboardInterrupt) as exc:
        error = str(exc) or 'Interrupted'
    finally:
        count = db.execute('select count(*) from records').fetchone()[0]
        files = render_exports(db, folder, state['complete'])
        db.close()
    manifest = {**state, 'at': now(), 'oqo': query, 'unique_records': count,
                'validation_count': validated['count'], 'error': error, 'files': files,
                'count_discrepancy': any(c != count for c in [validated['count'], *state['counts']]),
                'note': 'Cursor traversal of a changing index, not an immutable historical snapshot. CSV formula-like cells are escaped; original values are in JSONL.'}
    ws.put(str(folder.relative_to(ws.root) / 'export-manifest.json'), manifest)
    return {'ok': state['complete'], 'directory': str(folder), **manifest}
