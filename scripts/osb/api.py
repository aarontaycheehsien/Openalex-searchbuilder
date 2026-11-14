"""OpenAlex transport. Network evidence is never inferred from local text matching."""
from __future__ import annotations
import json
import re
import time
from urllib import request, error, parse
from .core import Error, digest, read, write, work_id
from .config import read_env

class ApiError(Error):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

class Client:
    def __init__(self, ws, *, fresh=False, opener=None, sleep=time.sleep):
        ws.require_online()
        self.ws, self.fresh = ws, fresh
        self.key = read_env('OPENALEX_API_KEY')
        self.opener = opener or request.urlopen
        self.sleep = sleep
        self.last_call = 0.0

    def clean(self, value):
        text = json.dumps(value, ensure_ascii=False)
        if self.key:
            text = text.replace(self.key, '[REDACTED]')
        text = re.sub(r'(?i)(api_key[=\s:]+)[^&\s"\\]+', r'\1[REDACTED]', text)
        return json.loads(text)

    def request(self, path, payload=None, params=None, cache=True):
        self.ws.require_online()
        method = 'POST' if payload is not None else 'GET'
        params = params or {}
        cache_key = digest([method, path, payload, params])
        cache_path = self.ws.root / '.cache' / (cache_key + '.json')
        if cache and not self.fresh and read_env('OSB_CACHE', '1') != '0':
            hit = read(cache_path)
            if hit is not None:
                self.ws.log({'event': 'request', 'request_hash': cache_key, 'cache': True})
                return hit
        url = 'https://api.openalex.org' + path
        if params:
            url += '?' + parse.urlencode(params)
        headers = {'Accept': 'application/json', 'User-Agent': 'openalex-search-builder/0.1'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        req = request.Request(url, data=body, headers=headers, method=method)
        for attempt in range(4):
            wait = .12 - (time.monotonic() - self.last_call)
            if wait > 0:
                self.sleep(wait)
            self.last_call = time.monotonic()
            try:
                with self.opener(req, timeout=45) as response:
                    data = json.load(response)
                    usage = {k: response.headers.get(k) for k in
                             ('X-RateLimit-Remaining', 'X-RateLimit-Credits-Used', 'X-RateLimit-Reset')}
                if not isinstance(data, dict):
                    raise ApiError('Unexpected API response shape')
                data = self.clean(data)
                self.ws.log(self.clean({'event': 'request', 'request_hash': cache_key, 'method': method,
                            'path': path, 'body': payload, 'params': params, 'usage': usage,
                            'cost': data.get('meta', {}).get('cost'), 'cache': False, 'ok': True}))
                if cache:
                    write(cache_path, data)
                return data
            except error.HTTPError as exc:
                with exc:
                    detail = self.clean(exc.read().decode('utf-8', errors='replace')[:3000])
                self.ws.log({'event': 'request_error', 'request_hash': cache_key, 'status': exc.code, 'detail': detail})
                retry_after = exc.headers.get('Retry-After', '') if exc.headers else ''
                budget = bool(re.search('budget|quota|daily|credit', detail, re.I))
                if exc.code in {429, 500, 502, 503, 504} and not budget and attempt < 3:
                    delay = float(retry_after) if retry_after.isdigit() else 2 ** attempt
                    if delay <= 30:
                        self.sleep(delay)
                        continue
                raise ApiError(f'OpenAlex HTTP {exc.code}: {detail}', exc.code) from None
            except (error.URLError, TimeoutError, OSError) as exc:
                if attempt < 3:
                    self.sleep(2 ** attempt)
                    continue
                raise ApiError('OpenAlex unavailable after bounded retries: ' + self.clean(str(exc))) from None
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ApiError('OpenAlex returned invalid JSON') from None

    def validate(self, oqo):
        data = self.request('/query', {'oqo': oqo})
        if data.get('validation', {}).get('valid') is not True or not data.get('oqo') or not data.get('oql'):
            raise ApiError('OpenAlex query contract not satisfied: missing valid validation, canonical OQO or OQL')
        return data

    def search(self, oqo, *, per_page=1, cursor=None, select=None):
        payload = {'oqo': oqo, 'per_page': per_page}
        if cursor is not None:
            payload['cursor'] = cursor
        if select:
            payload['select'] = select
        data = self.request('/', payload, cache=cursor is None)
        if not isinstance(data.get('results'), list) or not isinstance(data.get('meta', {}).get('count'), int):
            raise ApiError('OpenAlex execution contract not satisfied: results/meta.count missing')
        return data

    def among(self, oqo, ids):
        ids = sorted({work_id(i) for i in ids})
        found = set()
        for start in range(0, len(ids), 50):
            chunk = ids[start:start+50]
            clause = {'join': 'or', 'filters': [{'column_id': 'ids.openalex', 'value': i} for i in chunk]}
            q = {**oqo, 'filter_rows': [*oqo.get('filter_rows', []), clause]}
            data = self.search(q, per_page=100, select='id')
            if data['meta']['count'] > len(data['results']):
                raise ApiError('ID intersection was unexpectedly truncated')
            found.update(work_id(r['id']) for r in data['results'])
        return found

    def fetch(self, ids):
        result = []
        for value in ids:
            identifier = work_id(value)
            try:
                result.append(self.request('/works/' + identifier))
            except ApiError as exc:
                if exc.status != 404:
                    raise
        return result

    def resolve(self, value):
        raw = value.strip()
        try:
            target = work_id(raw)
        except Error:
            doi = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:)', '', raw, flags=re.I)
            if re.fullmatch(r'10\.\d{4,9}/\S+', doi):
                target = 'https://doi.org/' + doi
            elif re.fullmatch(r'(pmid:)?\d+', raw, re.I):
                target = 'pmid:' + raw.split(':')[-1]
            elif re.fullmatch(r'(pmcid:)?PMC\d+', raw, re.I):
                target = 'pmcid:' + raw.split(':')[-1].upper()
            else:
                return {'input': raw, 'status': 'unresolved', 'reason': 'Supply an OpenAlex ID, DOI, PMID or PMCID'}
        try:
            data = self.request('/works/' + parse.quote(target, safe=''))
            identifier = work_id(data['id'])
            return {'input': raw, 'status': 'resolved', 'id': identifier, 'record': data}
        except ApiError as exc:
            if exc.status == 404:
                return {'input': raw, 'status': 'unresolved', 'reason': 'Not found in OpenAlex'}
            raise

    def vocabulary(self, entity, query):
        if entity not in {'keywords', 'topics'}:
            raise Error('Use keywords or topics')
        return self.request('/' + entity, params={'search': query, 'per_page': 10})

    def neighbors(self, identifier, kind, corpus):
        records = self.fetch([identifier])
        if not records:
            return []
        if kind in {'references', 'related'}:
            return self.fetch(records[0].get('referenced_works' if kind == 'references' else 'related_works', []))
        q = {'get_rows': 'works', 'corpus': corpus,
             'filter_rows': [{'column_id': 'cites', 'value': work_id(identifier)}]}
        return self.search(q, per_page=100)['results']

def abstract(record):
    index = record.get('abstract_inverted_index') or {}
    pairs = [(p, word) for word, positions in index.items() for p in positions if isinstance(p, int) and p >= 0]
    return ' '.join(word for _, word in sorted(pairs))
