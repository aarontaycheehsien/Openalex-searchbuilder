"""Single JSON CLI for the agent workflow."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random
import sys
from .core import Error, Workspace, read, work_id, now
from .config import read_env
from .api import Client
from .strategy import FIELDS, prepare, lint
from .workflow import draft, evaluate, critic_packet, check_critic, report, terms
from .export import export

def parser():
    p = argparse.ArgumentParser(description='OpenAlex search development: agent writes concepts, CLI measures and audits.')
    p.add_argument('--workspace', '-w', default='.')
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('init'); q.add_argument('directory'); q.add_argument('--question', required=True)
    q.add_argument('--mode', choices=['draft', 'validated'], default='validated')
    q.add_argument('--depth', choices=['quick', 'standard', 'thorough'], default='standard')
    sub.add_parser('doctor')
    for c in ['status', 'draft', 'lint', 'count', 'export', 'log']:
        sub.add_parser(c)
    q = sub.add_parser('mode'); q.add_argument('value', choices=['draft', 'validated'])
    q = sub.add_parser('configure'); q.add_argument('--fields', choices=list(FIELDS)); q.add_argument('--corpus', choices=['core', 'all', 'expansion']); q.add_argument('--matching', choices=['stemmed', 'exact'])
    q = sub.add_parser('scope'); q.add_argument('--confirm', action='store_true')
    q = sub.add_parser('eval'); q.add_argument('--note', default=''); q.add_argument('--fresh', action='store_true')
    q = sub.add_parser('report'); q.add_argument('--diagnostic', action='store_true')
    q = sub.add_parser('resolve'); q.add_argument('ids', nargs='+')
    q = sub.add_parser('fetch'); q.add_argument('ids', nargs='+')
    q = sub.add_parser('sample'); q.add_argument('--purpose', choices=['pilot', 'prior-reviews', 'noise-check'], required=True); q.add_argument('--size', type=int, default=20)
    q = sub.add_parser('neighbors'); q.add_argument('id'); q.add_argument('--kind', choices=['references', 'citing', 'related'], default='related')
    q = sub.add_parser('vocab'); q.add_argument('entity', choices=['keywords', 'topics']); q.add_argument('query')
    q = sub.add_parser('screen'); q.add_argument('ids', nargs='+'); q.add_argument('--decision', choices=['include', 'exclude', 'uncertain'], required=True); q.add_argument('--reason', required=True)
    q = sub.add_parser('set'); q.add_argument('action', choices=['add', 'remove', 'list', 'split']); q.add_argument('name', nargs='?', default='seeds'); q.add_argument('ids', nargs='*'); q.add_argument('--role', choices=['seed', 'relevant', 'validation', 'benchmark'], default='seed'); q.add_argument('--source', default=''); q.add_argument('--note', default=''); q.add_argument('--fraction', type=float, default=.3)
    q = sub.add_parser('terms'); q.add_argument('action', choices=['rank', 'miss'])
    q = sub.add_parser('critic'); q.add_argument('action', choices=['packet', 'check']); q.add_argument('--file')
    q = sub.add_parser('progress'); q.add_argument('stage', choices=['intake', 'scope', 'known-records', 'vocabulary', 'test', 'critic', 'deliver'])
    q = sub.add_parser('cache'); q.add_argument('action', choices=['clear', 'status'])
    return p

def progress(ws, stage):
    e = ws.get('evaluation.json', {})
    p = ws.get('protocol.json')
    current = e.get('input_sha256') == ws.fingerprint()
    text = f"{stage}: {p['mode']} mode; fields={ws.get('strategy.json')['search_fields']}; corpus={ws.get('strategy.json')['corpus']}."
    if stage == 'scope':
        text += '\n' + '\n'.join(f"{c['id']}: {c.get('role')} — {c.get('rationale', '')}" for c in p['concepts'])
    if stage == 'test':
        text += f" Current evaluation: {current}." + (f" Retrieved {e['count']} works." if current else '')
    if stage == 'deliver':
        m = ws.get('validation-manifest.json', {})
        text += ' Validated artifacts available; human PRESS review recommended.' if m.get('input_sha256') == ws.fingerprint() and m.get('ok') else ' No current validated delivery.'
    return {'stage': stage, 'text': text}

def dispatch(a):
    if a.command == 'doctor':
        return {'ok': True, 'python': sys.version.split()[0], 'api_key_configured': bool(read_env('OPENALEX_API_KEY')),
                'live_integration': 'unverified; run opt-in live tests', 'draft_mode': 'offline; no key required'}
    if a.command == 'init':
        ws = Workspace.create(a.directory, a.question, a.mode, a.depth)
        return {'ok': True, 'workspace': str(ws.root), 'next': 'Edit protocol.json and strategy.json using the skill instructions'}
    ws = Workspace(a.workspace)
    with ws.lock():
        return run(ws, a)

def run(ws, a):
    cmd = a.command
    if cmd == 'status':
        e = ws.get('evaluation.json', {}); m = ws.get('validation-manifest.json', {})
        return {'protocol': ws.get('protocol.json'), 'input_sha256': ws.fingerprint(),
                'evaluation_current': bool(e.get('ok') and e.get('input_sha256') == ws.fingerprint()),
                'delivery_current': bool(m.get('ok') and m.get('input_sha256') == ws.fingerprint()), 'sets': ws.sets()}
    if cmd == 'mode':
        p = ws.get('protocol.json'); p['mode'] = a.value; ws.put('protocol.json', p)
        return {'ok': True, 'mode': a.value, 'note': 'Previous draft files remain; evaluations must match current inputs'}
    if cmd == 'configure':
        s = ws.get('strategy.json')
        for key, value in [('search_fields', a.fields), ('corpus', a.corpus), ('matching', a.matching)]:
            if value is not None: s[key] = value
        ws.put('strategy.json', s); return s
    if cmd == 'scope':
        p = ws.get('protocol.json')
        if a.confirm:
            if not p['concepts']: raise Error('Define scope concepts first')
            p['scope_confirmed'] = True; ws.put('protocol.json', p)
        return {'concepts': p['concepts'], 'eligibility': p['eligibility'], 'confirmed': p['scope_confirmed']}
    if cmd == 'draft': return draft(ws)
    if cmd == 'lint': return {'ok': True, 'warnings': lint(ws.get('strategy.json'), ws.get('protocol.json'))}
    if cmd == 'screen':
        s = ws.get('screening.json', {})
        active = {i for g in ws.sets().values() for i in g['ids']}
        if a.decision != 'include' and {work_id(i) for i in a.ids} & active:
            raise Error('Remove records from known-relevant sets before screening them exclude or uncertain')
        for i in a.ids: s[work_id(i)] = {'decision': a.decision, 'reason': a.reason}
        ws.put('screening.json', s); return {'ok': True, 'screening': s}
    if cmd == 'set':
        groups = ws.sets()
        if a.action == 'list': return groups
        if a.action == 'add':
            old = groups.get(a.name, {'ids': []})
            if old.get('role', a.role) != a.role: raise Error('Remove the old set before changing roles')
            return ws.save_set(a.name, a.role, [*old['ids'], *a.ids], a.source, a.note)
        if a.name not in groups: raise Error('Unknown set')
        if a.action == 'remove':
            groups[a.name]['ids'] = sorted(set(groups[a.name]['ids']) - {work_id(i) for i in a.ids})
            if not a.ids: del groups[a.name]
            ws.put('sets.json', groups); return groups
        if not 0 < a.fraction < 1 or len(groups[a.name]['ids']) < 2: raise Error('Split needs at least two records and fraction between 0 and 1')
        if groups[a.name]['role'] not in {'seed', 'relevant'}: raise Error('Only development sets can be split')
        name = a.name + '-validation'
        if name in groups: raise Error('Validation set already exists')
        ids = list(groups[a.name]['ids']); random.Random(0).shuffle(ids)
        n = min(len(ids)-1, max(1, round(len(ids)*a.fraction)))
        groups[name] = {**groups[a.name], 'role': 'validation', 'ids': sorted(ids[:n])}
        groups[a.name]['ids'] = sorted(ids[n:]); ws.put('sets.json', groups); return groups
    if cmd == 'critic':
        if a.action == 'packet': return critic_packet(ws)
        review = read(a.file) if a.file else None
        if review is not None:
            # Preserve the review even when its open findings correctly block delivery.
            # Later revision/closing packets must retain those objections.
            from .workflow import current_evaluation
            e = current_evaluation(ws)
            if review.get('input_sha256') != ws.fingerprint() or review.get('review_sha256') != e['review_sha256']:
                raise Error('Cannot import a stale critic response')
            ws.put('critic/review.json', review)
            ws.put('critic/import-' + str(__import__('time').time_ns()) + '.json', review)
        result = check_critic(ws, review)
        ws.put('critic/review.json', result)
        ws.put(f"critic/review-{result['round']:02}.json", result)
        return {'ok': True, 'review': result}
    if cmd == 'progress': return {'progress': progress(ws, a.stage)}
    if cmd == 'log': return {'requests': (ws.root / 'requests.jsonl').read_text() if (ws.root / 'requests.jsonl').exists() else ''}
    if cmd == 'cache':
        paths = list((ws.root / '.cache').glob('*.json'))
        if a.action == 'clear':
            for path in paths: path.unlink()
        return {'entries': len(paths), 'cleared': a.action == 'clear'}
    ws.require_online()
    client = Client(ws, fresh=getattr(a, 'fresh', False))
    if cmd == 'eval': return evaluate(ws, client, a.note)
    if cmd == 'report': return report(ws, diagnostic=a.diagnostic)
    if cmd == 'export': return export(ws, client)
    if cmd == 'terms': return terms(ws, client, a.action == 'miss')
    if cmd == 'resolve':
        results = [client.resolve(i) for i in a.ids]
        protected = {i for g in ws.sets().values() if g['role'] in {'validation', 'benchmark'} for i in g['ids']}
        for r in results:
            if r.get('id') in protected:
                r.pop('record', None)
        previous = ws.get('resolutions.json', {})
        for r in results: previous[r['input']] = {k: v for k, v in r.items() if k != 'record'}
        ws.put('resolutions.json', previous); return {'results': results}
    if cmd == 'fetch':
        protected = {i for g in ws.sets().values() if g['role'] in {'validation', 'benchmark'} for i in g['ids']}
        if {work_id(i) for i in a.ids} & protected:
            raise Error('Protected records cannot be inspected for vocabulary; reclassify as development first')
        return {'records': client.fetch(a.ids)}
    if cmd == 'vocab': return client.vocabulary(a.entity, a.query)
    if cmd == 'neighbors':
        protected = {i for g in ws.sets().values() if g['role'] in {'validation', 'benchmark'} for i in g['ids']}
        if work_id(a.id) in protected:
            raise Error('Do not use protected records for development discovery')
        records = client.neighbors(a.id, a.kind, ws.get('strategy.json')['corpus'])
    elif cmd in {'count', 'sample'}:
        q = prepare(ws.get('strategy.json'))['oqo']
        checked = client.validate(q)
        if cmd == 'count': return {'count': client.search(checked['oqo'])['meta']['count'], 'oql': checked['oql']}
        if not 1 <= a.size <= 100: raise Error('Sample size must be 1..100')
        records = client.search(checked['oqo'], per_page=a.size)['results']
    else:
        raise Error('Unknown command')
    protected = {i for g in ws.sets().values() if g['role'] in {'validation', 'benchmark'} for i in g['ids']}
    hidden = sum(work_id(r['id']) in protected for r in records)
    records = [r for r in records if work_id(r['id']) not in protected]
    candidates = ws.get('candidates.json', {})
    for r in records: candidates[work_id(r['id'])] = {'purpose': getattr(a, 'purpose', 'neighbors'), 'discovered_at': now()}
    ws.put('candidates.json', candidates)
    return {'records': records, 'protected_records_withheld': hidden,
            'note': 'Candidates require eligibility screening; these are bounded discovery results, not an exhaustive export.'}

def main(argv=None):
    try:
        result = dispatch(parser().parse_args(argv))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if isinstance(result, dict) and result.get('ok') is False else 0
    except (Error, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # Never print raw transport URLs or credentials from unhandled OS errors.
        message = str(exc) if isinstance(exc, Error) else f'Invalid input or local I/O error ({type(exc).__name__})'
        key = read_env('OPENALEX_API_KEY')
        if key: message = message.replace(key, '[REDACTED]')
        print(json.dumps({'ok': False, 'error': message})); return 1
