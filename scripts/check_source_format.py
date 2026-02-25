import json

with open('/home/jvsete/git/ai-log-analyzer/ai-data/source_logs_24h_cache.json') as f:
    data = json.load(f)

print('Type:', type(data).__name__)
if isinstance(data, dict):
    print('Keys:', list(data.keys()))
    if 'records' in data:
        records = data['records']
        print('Records count:', len(records))
        print('First record sample:')
        print(json.dumps(records[0], indent=2)[:1000])
elif isinstance(data, list):
    print('Array length:', len(data))
    print('First element sample:')
    print(json.dumps(data[0], indent=2)[:1000])
