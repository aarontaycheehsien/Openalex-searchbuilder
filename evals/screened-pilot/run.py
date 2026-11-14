"""Run the frozen screened-review pilot with PYTHONPATH=scripts and an API key."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

from osb.api import Client
from osb.core import Workspace, write
from osb.strategy import prepare


def run_topic(topic, revision, directory):
    name = topic['dataset']
    url = (f'https://raw.githubusercontent.com/asreview/synergy-dataset/{revision}/'
           f'datasets/{name}/output/{name}.csv')
    with urlopen(url, timeout=60) as response:
        source = response.read()
    rows = csv.DictReader(io.StringIO(source.decode('utf-8-sig'), newline=''))
    ws = Workspace.create(directory / name, f'Screened pilot: {name}')
    client = Client(ws, fresh=True)
    records = []
    for row in rows:
        if row['label_included'] != '1':
            continue
        doi = (row.get('doi') or '').strip()
        record = {'source_id': row['record_id'], 'doi': doi, 'id': None}
        if doi:
            resolution = client.resolve(doi)
            record['id'] = resolution.get('id')
            record['status'] = resolution['status']
        else:
            record['status'] = 'no_doi'
        records.append(record)
    ids = {row['id'] for row in records if row['id']}
    query = prepare(topic['strategy'])['oqo']
    result = {'dataset': name, 'source_url': url, 'source_sha256': hashlib.sha256(source).hexdigest(),
              'records': records, 'query': query, 'runs': []}
    output = ws.root / 'pilot-results.json'
    write(output, result)
    if not ids:
        print(name, len(records), "included rows, no resolved identifiers")
        return
    for _ in range(3):
        checked = client.validate(query)
        present = client.among({'get_rows': 'works', 'corpus': query['corpus'], 'filter_rows': []}, ids)
        hits = client.among(checked['oqo'], present)
        result['runs'].append({'count': client.search(checked['oqo'])['meta']['count'],
                               'in_corpus': sorted(present), 'retrieved': sorted(hits),
                               'oql': checked['oql']})
        write(output, result)
    print(name, len(records), len(ids), [(len(r['in_corpus']), len(r['retrieved'])) for r in result['runs']])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='New directory for results and request logs')
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(__file__).with_name('protocol.json').read_text(encoding='utf-8'))
    for entry in protocol['topics']:
        run_topic(entry, protocol['source_commit'], args.directory)
