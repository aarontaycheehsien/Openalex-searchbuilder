"""Concept-block compilation, adapted from upstream strategy.py.

Local parsing is deliberately narrower than arbitrary Elasticsearch syntax.
Service validation remains mandatory for validated delivery.
"""
from __future__ import annotations
from copy import deepcopy
import re
from .core import Error

FIELDS = {'title_abstract_keywords': 'title_abstract_keywords.search',
          'title_abstract': 'title_and_abstract.search', 'fulltext': 'fulltext.search'}
TOKEN = re.compile(r'\s*("(?:[^"\\]|\\.)*"(?:~\d+)?|\(|\)|[^\s()"]+)')

def parse(text, *, preserve_word_runs=False):
    if not isinstance(text, str) or not text.strip():
        raise Error('Empty expression')
    tokens, pos = [], 0
    while pos < len(text.rstrip()):
        m = TOKEN.match(text, pos)
        if not m:
            raise Error('Unbalanced quotation marks')
        tokens.append(m.group(1)); pos = m.end()
    if preserve_word_runs:
        # In native OQL a run of bare words forms one search operand.
        grouped = []
        previous_bare = False
        for token in tokens:
            bare = token not in {'(', ')'} and token.upper() not in {'AND', 'OR', 'NOT'} and not token.startswith('"')
            if bare and previous_bare:
                grouped[-1] += ' ' + token
            else:
                grouped.append(token)
            previous_bare = bare
        tokens = grouped
    depth = 0
    for token in tokens:
        depth += (token == '(') - (token == ')')
        if depth > 64:
            raise Error('Boolean nesting exceeds the supported depth of 64')
    at = 0
    def operand():
        nonlocal at
        if at >= len(tokens):
            raise Error('Missing Boolean operand')
        t = tokens[at]; at += 1
        if t == 'NOT':
            return ('not', operand())
        if t == '(':
            node = expression(0)
            if at >= len(tokens) or tokens[at] != ')':
                raise Error('Unbalanced parentheses')
            at += 1
            return node
        if t in {'AND', 'OR', ')'}:
            raise Error('Unexpected Boolean operator or parenthesis')
        if t.lower() in {'and', 'or', 'not'}:
            raise Error('Use uppercase Boolean operators, or quote literal operator words')
        if re.search(r'[\[\]{}:^\\]', t):
            raise Error('PubMed tags and unrecognized field syntax are not supported')
        if '~' in t and not re.fullmatch(r'"[^"\n]+"~\d+', t):
            raise Error('Use quoted-phrase proximity: "words here"~N')
        return ('term', t)
    def expression(minimum):
        nonlocal at
        left = operand()
        while at < len(tokens) and tokens[at] != ')':
            t = tokens[at]
            op = t if t in {'AND', 'OR', 'NOT'} else 'AND'
            precedence = 1 if op == 'OR' else 2
            if precedence < minimum:
                break
            if t in {'AND', 'OR', 'NOT'}:
                at += 1
            right = expression(precedence + 1)
            join = 'and' if op == 'NOT' else op.lower()
            right = ('not', right) if op == 'NOT' else right
            # Flatten associative chains: review strategies routinely have thousands
            # of OR terms and must not consume one Python stack frame per term.
            left = (join, *(left[1:] if left[0] == join else (left,)),
                    *(right[1:] if right[0] == join else (right,)))
        return left
    node = expression(0)
    if at != len(tokens):
        raise Error('Unbalanced parentheses')
    return node

def render(node):
    if node[0] == 'term':
        return node[1]
    if node[0] == 'not':
        return 'NOT (' + render(node[1]) + ')'
    return '(' + (' ' + node[0].upper() + ' ').join(render(n) for n in node[1:]) + ')'

def to_filter(node, field, matching, *, native=False, negated=False):
    if node[0] == 'term':
        text = node[1]
        if '*' in text or '?' in text:
            if matching != 'exact':
                raise Error('Wildcards require matching="exact"; select it explicitly, then evaluate the changed semantics')
            for word in re.findall(r'[\w*?]+', text):
                if '*' in word or '?' in word:
                    prefix = re.split(r'[*?]', word)[0]
                    if len(prefix) < 3:
                        raise Error('Wildcards require at least three leading characters')
            if '~' in text:
                raise Error('Wildcard proximity is not supported by this compiler')
        if native and '~' in text:
            phrase, distance = text[1:].rsplit('"~', 1)
            words = phrase.split()
            if len(words) < 2:
                raise Error('Native OQL proximity requires at least two words')
            # OQO emitted by POST /query for an OQL "within N words" operand.
            text = f'"{words[0]}"~{distance}~' + '~'.join(f'"{word}"' for word in words[1:])
        leaf = {'column_id': field + ('.exact' if matching == 'exact' else ''), 'operator': 'has', 'value': text}
        if negated:
            leaf['is_negated'] = True
        return leaf
    if node[0] == 'not':
        return to_filter(node[1], field, matching, native=native, negated=not negated)
    join = node[0]
    if negated:
        join = 'or' if join == 'and' else 'and'
    return {'join': join, 'filters': [to_filter(n, field, matching, native=native, negated=negated)
                                      for n in node[1:]]}

def prepare(strategy):
    s = deepcopy(strategy)
    field = FIELDS.get(s.get('search_fields', 'title_abstract_keywords'))
    if field is None or s.get('corpus', 'all') not in {'all', 'core', 'expansion'}:
        raise Error('Invalid search_fields or corpus')
    if s.get('matching', 'stemmed') not in {'stemmed', 'exact'}:
        raise Error('matching must be stemmed or exact')
    proximity_mode = s.get('proximity_mode', 'phrase_slop')
    if proximity_mode not in {'phrase_slop', 'oql'}:
        raise Error('proximity_mode must be phrase_slop or oql')
    blocks, raw_blocks = {}, {}
    for b in s.get('blocks', []):
        key = b.get('id', '')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key) or key.upper() in {'AND', 'OR', 'NOT'} or key in blocks:
            raise Error('Invalid or duplicate concept ID')
        if not b.get('terms') or not all(isinstance(t, str) and t.strip() for t in b['terms']):
            raise Error('Every block needs nonempty string terms')
        raw = '(' + ' OR '.join('(' + t + ')' for t in b['terms']) + ')'
        raw_blocks[key] = ('term', raw)
        blocks[key] = parse(raw)
    if not blocks:
        raise Error('Add concept blocks to strategy.json first')
    combination = parse(s.get('combine') or ' AND '.join(blocks))
    def substitute(node, values):
        if node[0] == 'term':
            if node[1] not in blocks:
                raise Error('Unknown block in combine: ' + node[1])
            return values[node[1]]
        return (node[0], *(substitute(n, values) for n in node[1:]))
    boolean = render(substitute(combination, raw_blocks))
    native = proximity_mode == 'oql' and '~' in boolean
    if native:
        blocks = {key: parse(node[1], preserve_word_runs=True) for key, node in raw_blocks.items()}
    tree = substitute(combination, blocks)
    # OpenAlex validates a bare proximity phrase but errors on redundant wrappers.
    if tree[0] == 'term':
        boolean = render(tree)
    matching = s.get('matching', 'stemmed')
    structured = to_filter(tree, field, matching, native=native)
    # Send the Boolean expression as ONE scoped text search. Separating every word
    # into a distinct search filter changes stop-word and automatic keyword behavior.
    filters = [{'column_id': field + ('.exact' if matching == 'exact' else ''),
                'operator': 'has', 'value': boolean}]
    if native:
        filters = [structured]
    for limit in s.get('limits', []):
        if not limit.get('rationale', '').strip():
            raise Error('Each limit needs a rationale')
        node = limit.get('filter')
        if not isinstance(node, dict) or set(node) - {'column_id', 'value', 'operator', 'is_negated'} or not {'column_id', 'value'} <= set(node):
            raise Error('Limits need a structured OQO leaf filter')
        if not isinstance(node['column_id'], str) or '.search' in node['column_id']:
            raise Error('Put search expressions in concept blocks, not limits')
        filters.append(deepcopy(node))
    return {'boolean': boolean, 'oqo': {'get_rows': 'works', 'corpus': s.get('corpus', 'all'), 'filter_rows': filters}}

def lines(strategy):
    result = []
    for b in strategy['blocks']:
        for t in b['terms']:
            s = {**strategy, 'blocks': [{**b, 'terms': [t]}], 'combine': None, 'limits': []}
            result.append({'kind': 'term', 'block': b['id'], 'text': t, **prepare(s)})
        s = {**strategy, 'blocks': [b], 'combine': None, 'limits': []}
        result.append({'kind': 'block', 'block': b['id'], **prepare(s)})
    result.append({'kind': 'core', **prepare({**strategy, 'limits': []})})
    for i in range(len(strategy.get('limits', []))):
        result.append({'kind': 'limit', **prepare({**strategy, 'limits': strategy['limits'][:i+1]})})
    return [dict(n=i + 1, **row) for i, row in enumerate(result)]

def lint(strategy, protocol):
    prepare(strategy)
    issues = []
    for b in strategy['blocks']:
        if len(set(t.casefold().strip() for t in b['terms'])) != len(b['terms']):
            issues.append('Duplicate terms in ' + b['id'])
    concepts = {c['id']: c for c in protocol.get('concepts', [])}
    block_ids = {b['id'] for b in strategy['blocks']}
    for key in block_ids:
        if key not in concepts or concepts[key].get('role') != 'search':
            issues.append('Block is not a searched scope concept: ' + key)
    for key, c in concepts.items():
        if c.get('role') == 'search' and key not in block_ids:
            issues.append('Searched scope concept has no block: ' + key)
    if 'NOT' in prepare(strategy)['boolean']:
        issues.append('NOT may exclude relevant records; document its rationale')
    return issues
