"""Evaluation, evidence-bound critique and protected delivery adapted from upstream."""
from __future__ import annotations
from copy import deepcopy
from collections import Counter
import json
import re
from .core import Error, atomic, digest, now, work_id
from .strategy import prepare, lines, lint
from .api import Client, abstract

LABEL = 'Untested draft — not validated against OpenAlex.'

def draft(ws):
    p, s = ws.get('protocol.json'), ws.get('strategy.json')
    if p['mode'] != 'draft':
        raise Error('Select `mode draft` first')
    query = prepare(s)
    issues = lint(s, p)
    data = {'status': 'untested', 'label': LABEL, 'input_sha256': ws.fingerprint(),
            'search_fields': s['search_fields'], 'matching': s['matching'], 'corpus': s['corpus'],
            'boolean': query['boolean'], 'request': {'method': 'POST', 'url': 'https://api.openalex.org/',
            'body': {'oqo': query['oqo']}}, 'local_warnings': issues}
    ws.put('draft-query.json', data)
    atomic(ws.root / 'draft-query.txt', LABEL + '\n\n' + query['boolean'] + '\n\n' +
           f"Fields: {s['search_fields']}\nMatching: {s['matching']}\nCorpus: {s['corpus']}\n" +
           'Limits: ' + json.dumps(s['limits'], ensure_ascii=False) + '\n')
    atomic(ws.root / 'draft-notes.md', '# Untested draft\n\n' + LABEL +
           '\n\nNo API requests, vocabulary verification, retrieval testing or live validation were performed. '
           'Local checks do not establish service acceptance, recall, or coverage.\n\n' +
           json.dumps({'question': p['question'], 'eligibility': p['eligibility'], 'notes': p['notes'],
                       'warnings': issues}, indent=2, ensure_ascii=False) + '\n')
    return data

def review_fingerprint(e):
    return digest({k: e.get(k) for k in ('input_sha256', 'oqo', 'oql', 'known', 'sets', 'misses', 'warnings', 'canonical_lines')})

def evaluate(ws, client=None, note='', save=True):
    ws.require_online()
    client = client or Client(ws)
    inputs = ws.snapshot()
    s, p = inputs['strategy'], inputs['protocol']
    query = prepare(s)
    result = {'at': now(), 'input_sha256': digest(inputs), 'inputs': inputs, 'note': note,
              'ok': False, 'lines': [], 'warnings': lint(s, p), 'boolean': query['boolean'], 'oqo': query['oqo']}
    try:
        canonical = client.validate(query['oqo'])
        result.update(oqo=canonical['oqo'], oql=canonical['oql'])
        result['warnings'].extend(json.dumps(w, sort_keys=True) for w in canonical.get('validation', {}).get('warnings', []))
        result['count'] = client.search(result['oqo'])['meta']['count']
        for line in lines(s):
            checked = client.validate(line['oqo'])
            count = client.search(checked['oqo'])['meta']['count']
            result['lines'].append({**line, 'count': count, 'canonical': checked['oqo'], 'oql': checked['oql']})
            result['warnings'].extend(json.dumps(w, sort_keys=True) for w in checked.get('validation', {}).get('warnings', []))
            if count == 0 and line['kind'] == 'term':
                result['warnings'].append('Zero-hit term: ' + line['text'])
        result['canonical_lines'] = [line['canonical'] for line in result['lines']]
        ids = sorted({i for group in ws.sets().values() for i in group['ids']})
        records = client.fetch(ids)
        indexed = {work_id(r['id']) for r in records}
        present = client.among({'get_rows': 'works', 'corpus': s['corpus'], 'filter_rows': []}, indexed)
        hits = client.among(result['oqo'], present)
        core = prepare({**s, 'limits': []})['oqo']
        core_hits = client.among(core, present) if s['limits'] else hits
        by_block = {b['id']: client.among(prepare({**s, 'blocks': [b], 'combine': None, 'limits': []})['oqo'], present) for b in s['blocks']}
        result['known'] = {'indexed': sorted(indexed), 'in_corpus': sorted(present), 'retrieved': sorted(hits),
                           'unavailable': sorted(set(ids) - indexed), 'outside_corpus': sorted(indexed - present)}
        result['sets'] = {}
        for name, group in ws.sets().items():
            members = set(group['ids']); eligible = members & present
            result['sets'][name] = {'role': group['role'], 'size': len(members), 'in_corpus': len(eligible),
                'coverage_percent': 100 * len(eligible) / len(members) if members else None,
                'retrieved': len(members & hits), 'relative_recall_percent': 100 * len(members & hits) / len(eligible) if eligible else None,
                'missed': sorted(eligible - hits), 'unavailable': sorted(members - indexed), 'outside_corpus': sorted((members & indexed) - present)}
        result['misses'] = [{'id': i, 'failing_blocks': [b for b, found in by_block.items() if i not in found],
                              'lost_to_limits': i in core_hits} for i in sorted(present - hits)]
        result['block_recall'] = {b: {'retrieved': len(found), 'of': len(present)} for b, found in by_block.items()}
        result['ablation'] = []
        if not s.get('combine') and len(s['blocks']) > 1:
            for block in s['blocks']:
                q = prepare({**s, 'blocks': [b for b in s['blocks'] if b['id'] != block['id']], 'limits': []})['oqo']
                result['ablation'].append({'drop': block['id'], 'count': client.search(q)['meta']['count'],
                                          'known_gained': sorted(client.among(q, present) - core_hits)})
        elif s.get('combine'):
            result['ablation_note'] = 'Ablation requires the default AND combination; not performed for custom Boolean trees.'
        if not ids:
            result['warnings'].append('No known records: relative recall was not measured')
        if result['misses']:
            result['warnings'].append('Known-record misses require explanation')
        previous = ws.get('evaluation.json', {})
        old = set(previous.get('known', {}).get('retrieved', []))
        result['known_lost'] = sorted((old & present) - hits)
        if result['known_lost'] and not note.strip():
            raise Error('Previously retrieved known records were lost; provide a reason in --note or revert')
        if ws.fingerprint() != result['input_sha256']:
            raise Error('Workspace inputs changed during evaluation')
        result['warnings'] = sorted(set(result['warnings']))
        result['review_sha256'] = review_fingerprint(result)
        result['ok'] = True
    except Error as exc:
        result['error'] = str(exc)
    if save:
        ws.put('attempts/' + str(__import__('time').time_ns()) + '.json', result)
        if result['ok']:
            ws.put('evaluation.json', result)
            ws.put('history/' + str(__import__('time').time_ns()) + '.json', result)
    return result

def current_evaluation(ws):
    e = ws.get('evaluation.json', {})
    if not e.get('ok') or e.get('input_sha256') != ws.fingerprint():
        raise Error('Run eval for the current workspace inputs before critique or delivery')
    return e

def critic_packet(ws):
    e = current_evaluation(ws)
    packets = sorted((ws.root / 'critic').glob('packet-*.json')) if (ws.root / 'critic').exists() else []
    depth = ws.get('protocol.json')['depth']
    revision_limit = {'quick': 1, 'standard': 2, 'thorough': 3}[depth]
    number = len(packets) + 1
    phase = 'revision' if number <= revision_limit else 'closing' if number == revision_limit + 1 else 'verification'
    if number > revision_limit + 2:
        raise Error('Critique round budget exhausted; deliver diagnostics rather than bypassing review')
    packet = {'round': number, 'phase': phase, 'input_sha256': ws.fingerprint(),
              'review_sha256': e['review_sha256'], 'evaluation': e,
              'previous_review': ws.get('critic/review.json'),
              'instructions': 'PRESS-structured internal critique: scope, vocabulary, Boolean logic, field/corpus choices, limits, known misses, and reporting. Closing/verification address previous findings; technical defects always block. Do not mine protected records.',
              'response_template': {'input_sha256': ws.fingerprint(), 'review_sha256': e['review_sha256'],
                                    'round': number, 'reviewer': '', 'fresh_context': True,
                                    'summary': '', 'warnings_reviewed': e['warnings'],
                                    'findings': []},
              'finding_schema': {'id': 'unique ID', 'kind': 'technical|scope|lexical|reporting',
                                 'severity': 'must-fix|advisory', 'message': 'finding',
                                 'status': 'open|resolved|rejected|accepted-risk', 'response': 'evidence/reason'}}
    ws.put(f'critic/packet-{number:02}.json', packet)
    return packet

def check_critic(ws, review=None):
    e = current_evaluation(ws)
    review = review if review is not None else ws.get('critic/review.json', {})
    if review.get('input_sha256') != ws.fingerprint() or review.get('review_sha256') != e['review_sha256']:
        raise Error('Critic is missing or stale for these inputs and retrieval evidence')
    packets = sorted((ws.root / 'critic').glob('packet-*.json'))
    if not packets:
        raise Error('Generate a critic packet first')
    packet = ws.get(str(packets[-1].relative_to(ws.root)))
    if review.get('round') != packet['round'] or packet['review_sha256'] != e['review_sha256']:
        raise Error('Review does not correspond to the latest packet')
    if not review.get('reviewer', '').strip() or not review.get('summary', '').strip() or not isinstance(review.get('fresh_context'), bool):
        raise Error('Review requires reviewer, substantive summary, and fresh_context boolean')
    if sorted(review.get('warnings_reviewed', [])) != sorted(e['warnings']):
        raise Error('Reviewer must acknowledge every current warning')
    findings = review.get('findings')
    if not isinstance(findings, list):
        raise Error('Review findings must be a list')
    seen = set()
    for f in findings:
        if not f.get('id') or f['id'] in seen or not f.get('message'):
            raise Error('Findings need unique IDs and messages')
        seen.add(f['id'])
        if f.get('kind') not in {'technical', 'scope', 'lexical', 'reporting'} or f.get('severity') not in {'must-fix', 'advisory'}:
            raise Error('Invalid finding kind or severity')
        if f.get('status') not in {'resolved', 'rejected', 'accepted-risk'} or not f.get('response', '').strip():
            raise Error('Every finding requires a closed, explained disposition')
        if f['kind'] == 'technical' and f['status'] != 'resolved':
            raise Error('Technical findings cannot be accepted or overridden')
    previous = packet.get('previous_review') or {}
    if packet['phase'] != 'revision':
        prior_ids = {f['id'] for f in previous.get('findings', [])}
        if not prior_ids <= seen:
            raise Error('Closing/verification must account for every earlier finding')
        if any(f['id'] not in prior_ids and f['severity'] == 'must-fix' and f['kind'] != 'technical' for f in findings):
            raise Error('Closing review cannot add new subjective must-fix findings')
    return review

def report(ws, client=None, diagnostic=False):
    ws.require_online()
    e = current_evaluation(ws)
    p = ws.get('protocol.json')
    if not p.get('scope_confirmed'):
        raise Error('Scope must be confirmed before validated delivery')
    if not p.get('concepts'):
        raise Error('Scope concepts are required')
    review = check_critic(ws)
    fresh = evaluate(ws, client or Client(ws, fresh=True), note=e.get('note', ''), save=False)
    if not fresh['ok']:
        raise Error('Fresh validation failed: ' + fresh.get('error', 'unknown error'))
    if fresh['review_sha256'] != e['review_sha256']:
        raise Error('Live interpretation or known-record evidence changed; evaluate and critique again')
    if diagnostic:
        return {'ok': True, 'diagnostic': True, 'evaluation': fresh}
    outputs = {'final-query.txt': fresh['oql'] + '\n',
               'final-query.json': json.dumps({'oqo': fresh['oqo'], 'oql': fresh['oql'],
                   'request': {'method': 'POST', 'url': 'https://api.openalex.org/', 'body': {'oqo': fresh['oqo']}}}, indent=2) + '\n'}
    audit = '# OpenAlex search audit\n\nDraft for human PRESS peer review. Internal critique is not formal peer review.\n\n'
    audit += f"Question: {p['question']}\n\nRun: {fresh['at']}\n\nFields: {ws.get('strategy.json')['search_fields']}; corpus: {ws.get('strategy.json')['corpus']}\n\n"
    audit += 'Search interpretation, coverage, known-record tests, limitations and critique follow. Development recall is not independent validation or complete sensitivity. OpenAlex changes over time; this is not a historical database snapshot.\n\n'
    audit += 'Keyword-enabled modes use OpenAlex automatic keyword matching; topics are not MeSH. Full-text mode searches available indexed text, not every article.\n\n'
    audit += '```json\n' + json.dumps({'evaluation': fresh, 'critic': review}, indent=2, ensure_ascii=False) + '\n```\n'
    outputs['audit.md'] = audit
    for name, text in outputs.items():
        atomic(ws.root / name, text)
    manifest = {'ok': True, 'at': now(), 'input_sha256': ws.fingerprint(), 'query_sha256': digest(fresh['oqo']),
                'oqo': fresh['oqo'], 'count': fresh['count'], 'review_sha256': fresh['review_sha256'],
                'files': {name: __import__('hashlib').sha256(text.encode()).hexdigest() for name, text in outputs.items()}}
    ws.put('validation-manifest.json', manifest)
    return manifest

def terms(ws, client, missed=False):
    allowed = set(ws.mining_ids())
    if missed:
        e = current_evaluation(ws)
        allowed &= {r['id'] for r in e['misses']}
    records = client.fetch(sorted(allowed))
    counts = Counter()
    for r in records:
        counts.update(set(re.findall(r'\b[^\W\d_]{3,}\b', (r.get('display_name', '') + ' ' + abstract(r)).lower())))
    return {'development_ids': sorted(allowed), 'terms': counts.most_common(100),
            'note': 'Protected validation/benchmark records are excluded. Reclassify before inspecting their vocabulary.'}
