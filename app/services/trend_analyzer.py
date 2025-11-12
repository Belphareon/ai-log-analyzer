"""Trend analyzer - handles large datasets with ES scroll API"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from collections import defaultdict

from app.services.elasticsearch import es_service
from app.services.pattern_detector import pattern_detector

class TrendAnalyzer:
    """Analyze error trends from large ES datasets"""
    
    async def fetch_errors_batch(
        self, 
        time_from: datetime, 
        time_to: datetime,
        batch_size: int = 10000,
        max_total: int = 50000
    ) -> List[Dict]:
        """
        Fetch errors in batches using scroll API
        
        Args:
            time_from: Start time
            time_to: End time
            batch_size: Size per batch (max 10k per ES limitation)
            max_total: Maximum total errors to fetch
        """
        await es_service.connect()
        
        all_errors = []
        
        # Initial query with scroll
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {
                            "gte": time_from.isoformat() + "Z", 
                            "lte": time_to.isoformat() + "Z"
                        }}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            },
            "size": batch_size,
            "_source": ["message", "kubernetes.labels.app", "@timestamp", "traceId", "kubernetes.namespace"]
        }
        
        # First batch
        response = await es_service.client.search(
            index=es_service.index_pattern,
            body=query,
            scroll='2m'  # Keep scroll context for 2 minutes
        )
        
        scroll_id = response.get('_scroll_id')
        hits = response['hits']['hits']
        total = response['hits']['total']['value']
        
        # Process first batch
        for hit in hits:
            src = hit['_source']
            all_errors.append({
                'message': src.get('message', ''),
                'app': src.get('kubernetes', {}).get('labels', {}).get('app', 'unknown'),
                'namespace': src.get('kubernetes', {}).get('namespace', 'unknown'),
                'timestamp': datetime.fromisoformat(src.get('@timestamp', '').replace('Z', '+00:00')),
                'trace_id': src.get('traceId')
            })
        
        # Fetch remaining batches
        while len(all_errors) < max_total and len(hits) > 0:
            response = await es_service.client.scroll(
                scroll_id=scroll_id,
                scroll='2m'
            )
            
            hits = response['hits']['hits']
            
            for hit in hits:
                if len(all_errors) >= max_total:
                    break
                    
                src = hit['_source']
                all_errors.append({
                    'message': src.get('message', ''),
                    'app': src.get('kubernetes', {}).get('labels', {}).get('app', 'unknown'),
                    'namespace': src.get('kubernetes', {}).get('namespace', 'unknown'),
                    'timestamp': datetime.fromisoformat(src.get('@timestamp', '').replace('Z', '+00:00')),
                    'trace_id': src.get('traceId')
                })
        
        # Clear scroll
        if scroll_id:
            await es_service.client.clear_scroll(scroll_id=scroll_id)
        
        return all_errors, total
    
    def calculate_coverage(self, sample_size: int, total: int) -> float:
        """Calculate sample coverage percentage"""
        return (sample_size / total * 100) if total > 0 else 0

trend_analyzer = TrendAnalyzer()
