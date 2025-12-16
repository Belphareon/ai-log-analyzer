import requests
from requests.auth import HTTPBasicAuth
import urllib3
from datetime import datetime, timedelta, timezone

urllib3.disable_warnings()

ES_URL = "https://elasticsearch-test.kb.cz:9500"
ES_USER = "XX_PCBS_ES_READ"
ES_PASSWORD = os.getenv('ES_PASSWORD', 'your_password_here')
ES_INDEX = "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*"

# Query last 7 days
now = datetime.now(timezone.utc)
start = now - timedelta(days=7)

query = {
    "size": 0,
    "query": {
        "bool": {
            "must": [
                {"term": {"level.keyword": "ERROR"}},
                {"range": {"@timestamp": {
                    "gte": start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "lte": now.strftime("%Y-%m-%dT%H:%M:%S")
                }}}
            ]
        }
    },
    "aggs": {
        "by_day": {
            "date_histogram": {
                "field": "@timestamp",
                "fixed_interval": "1d",
                "time_zone": "UTC"
            }
        },
        "by_namespace": {
            "terms": {"field": "kubernetes.namespace.keyword", "size": 20}
        }
    }
}

print(f"🔍 Checking data availability (last 7 days)")
print(f"Time range: {start.strftime('%Y-%m-%d')} - {now.strftime('%Y-%m-%d')}")
print("=" * 80)

try:
    response = requests.post(
        f"{ES_URL}/{ES_INDEX}/_search",
        json=query,
        auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
        verify=False,
        timeout=30
    )
    
    if response.status_code == 200:
        data = response.json()
        total = data['hits']['total']['value']
        
        print(f"\n✅ Query successful!")
        print(f"📊 Total errors in last 7 days: {total:,}")
        
        if total > 0:
            print(f"\n📋 Errors by day:")
            for bucket in data['aggregations']['by_day']['buckets']:
                date = bucket['key_as_string'][:10]
                count = bucket['doc_count']
                if count > 0:
                    print(f"   {date}: {count:,} errors")
            
            print(f"\n📦 Top namespaces:")
            for bucket in data['aggregations']['by_namespace']['buckets'][:10]:
                ns = bucket['key']
                count = bucket['doc_count']
                pct = (count / total) * 100
                print(f"   {ns}: {count:,} errors ({pct:.1f}%)")
        else:
            print("\n⚠️  No ERROR level logs found in last 7 days")
            print("   Možné příčiny:")
            print("   - Index pattern neodpovídá")
            print("   - Level field má jiný formát")
            print("   - Data jsou starší než 7 dní")
    else:
        print(f"❌ Error {response.status_code}: {response.text[:300]}")
        
except Exception as e:
    print(f"❌ Failed: {e}")

