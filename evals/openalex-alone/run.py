"""Run from the repo root with PYTHONPATH=scripts and an ignored local API key."""
import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.request import urlopen

from osb.api import Client
from osb.core import Workspace, work_id, write
from osb.strategy import prepare


def exercise_ids(case, client, ws):
    with urlopen(case['source_url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != case['sha256']:
        raise ValueError('Exercise citation file changed')
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    if len(rows) != case['denominator']:
        raise ValueError('Exercise citation denominator mismatch')
    ledger = [{'row': row['Covidence #'], 'doi': re.sub(r'^https?://(?:dx\.)?doi\.org/', '', row['DOI'].strip().lower()),
               'id': None} for row in rows]
    dois = sorted({r['doi'] for r in ledger if r['doi']})
    matched = {}
    for start in range(0, len(dois), 20):
        chunk = dois[start:start+20]
        page = client.request('/works', params={'filter': 'doi:' + '|'.join(chunk),
                              'per_page': 100, 'select': 'id,doi'})
        if page['meta']['count'] != len(page['results']):
            raise ValueError('Incomplete DOI lookup')
        for work in page['results']:
            doi = (work['doi'] or '').lower().removeprefix('https://doi.org/')
            if doi in chunk:
                matched.setdefault(doi, set()).add(work_id(work['id']))
    for record in ledger:
        candidates = matched.get(record['doi'], set())
        if len(candidates) == 1:
            record['id'] = next(iter(candidates))
    write(ws.root / 'exercise-mapping.json', ledger)
    return {r['id'] for r in ledger if r['id']}


def compare(case, revision, directory):
    base = f"https://raw.githubusercontent.com/aarontaycheehsien/canyouuseopenalexalone/{revision}/{case['folder']}/"

    def source(path):
        with urlopen(base + path, timeout=45) as response:
            return response.read().decode('utf-8-sig')

    ws = Workspace.create(directory / case['topic'], case['topic'])
    client = Client(ws, fresh=True)
    if case['topic'] == 'exercise':
        ids = exercise_ids(case, client, ws)
    elif case['topic'] == 'diabetic_eye_screening':
        ids = {work_id(i) for i in source('benchmark/benchmark_130_verified_ids.txt').splitlines()}
    else:
        rows = csv.DictReader(source('results/per_article_retrieval.csv').splitlines())
        ids = {work_id(row['openalex_id']) for row in rows}
    if case['topic'] != 'exercise' and len(ids) != case['denominator']:
        raise ValueError('Pinned benchmark denominator mismatch')
    present = client.among({'get_rows': 'works', 'corpus': 'core', 'filter_rows': []}, ids)
    aliases = {}
    for original in sorted(ids - present):
        resolution = client.resolve(original)
        if resolution.get('id') and resolution['id'] != original:
            aliases[original] = resolution['id']
    canonical = {aliases.get(i, i) for i in ids}
    if not present <= canonical:
        raise ValueError('Core intersection contains an unexplained ID')
    results = {'benchmark_ids': sorted(ids), 'verified_redirects': aliases,
               'current_core_ids': sorted(present), 'arms': {}}
    for arm in ['searchbuilder', *case['reference_arms']]:
        if arm == 'searchbuilder':
            checked = client.validate(prepare(case['strategy'])['oqo'])
        else:
            oql = source('queries/' + arm + '.oql').strip()
            checked = client.request('/query', {'oql': oql})
            if checked.get('validation', {}).get('valid') is not True:
                raise ValueError('Upstream OQL failed validation: ' + arm)
        query = checked['oqo']
        count = client.search(query, select='id')['meta']['count']
        found = client.among(query, canonical)
        hits = {i for i in ids if aliases.get(i, i) in found}
        if not found <= canonical:
            raise ValueError('Intersection yielded non-benchmark IDs')
        results['arms'][arm] = {'count': count, 'retrieved': sorted(hits),
                                'missed': sorted(ids - hits), 'oql': checked['oql']}
        write(ws.root / 'comparison.json', results)
        print(case['topic'], arm, len(hits), '/', len(ids), 'from', count, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(__file__).with_name('protocol.json').read_text(encoding='utf-8'))
    for case in [*protocol['cases'], dict(topic='exercise', **protocol['exercise'])]:
        compare(case, protocol['revision'], args.directory)
