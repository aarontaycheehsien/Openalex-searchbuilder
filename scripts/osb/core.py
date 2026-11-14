"""Workspace and evidence primitives adapted from PubMed Search Builder."""
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

class Error(ValueError):
    pass

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default

def write(path, value):
    atomic(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def work_id(value):
    value = str(value).strip().removeprefix('https://openalex.org/').removeprefix('http://openalex.org/')
    if not re.fullmatch(r'W[1-9][0-9]*', value, re.I):
        raise Error(f'Not an OpenAlex work ID: {value!r}; resolve external identifiers first')
    return value.upper()

ROLES = {'seed', 'relevant', 'validation', 'benchmark'}

class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if read(self.root / 'workspace.json') != {'schema': 1, 'provider': 'openalex'}:
            raise Error('Not an OpenAlex workspace (schema 1). PubMed workspaces cannot be imported.')

    @classmethod
    def create(cls, root, question, mode='validated', depth='standard'):
        root = Path(root)
        if root.exists() and any(root.iterdir()):
            raise Error('Workspace must be empty; existing runs are never overwritten')
        root.mkdir(parents=True, exist_ok=True)
        write(root / 'workspace.json', {'schema': 1, 'provider': 'openalex'})
        write(root / 'protocol.json', {'question': question, 'mode': mode, 'depth': depth,
              'scope_confirmed': False, 'concepts': [], 'eligibility': {'include': [], 'exclude': []}, 'notes': []})
        write(root / 'strategy.json', {'blocks': [], 'combine': None, 'limits': [],
              'search_fields': 'title_abstract_keywords', 'corpus': 'all', 'matching': 'stemmed'})
        write(root / 'sets.json', {})
        write(root / 'screening.json', {})
        return cls(root)

    @contextlib.contextmanager
    def lock(self):
        path = self.root / '.lock'
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise Error('Workspace is busy. Remove .lock only after confirming no command is running.')
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            path.unlink(missing_ok=True)

    def get(self, name, default=None):
        return read(self.root / name, default)

    def put(self, name, value):
        write(self.root / name, value)

    def log(self, event):
        with (self.root / 'requests.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': now(), **event}, ensure_ascii=False) + '\n')

    def snapshot(self):
        return {k: self.get(k + '.json', {}) for k in ('protocol', 'strategy', 'sets', 'screening', 'resolutions')}

    def fingerprint(self):
        return digest(self.snapshot())

    def require_online(self):
        if self.get('protocol.json')['mode'] == 'draft':
            raise Error('Draft mode is offline. Run `mode validated` to enable API commands.')

    def sets(self):
        return self.get('sets.json', {})

    def mining_ids(self):
        sets = self.sets().values()
        protected = {i for s in sets if s['role'] in {'validation', 'benchmark'} for i in s['ids']}
        return sorted({i for s in self.sets().values() if s['role'] in {'seed', 'relevant'} for i in s['ids']} - protected)

    def save_set(self, name, role, ids, source='', note=''):
        if role not in ROLES or not re.fullmatch(r'[\w-]+', name):
            raise Error('Invalid set name or role')
        ids = sorted({work_id(i) for i in ids})
        screens = self.get('screening.json', {})
        if role in {'relevant', 'benchmark'} and any(screens.get(i, {}).get('decision') != 'include' for i in ids):
            raise Error('Discovered and benchmark records must be screened include before set admission')
        sets = self.sets()
        for other, s in sets.items():
            if other != name and s['role'] != role and set(ids) & set(s['ids']):
                raise Error('Records cannot overlap roles. Remove from the old set before reclassifying.')
        sets[name] = {'role': role, 'ids': ids, 'source': source, 'note': note}
        self.put('sets.json', sets)
        return sets[name]
