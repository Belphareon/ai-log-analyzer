"""
Elasticsearch service for querying application logs.
Provides integration with Elasticsearch for log retrieval and analysis.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from elasticsearch import AsyncElasticsearch
from elasticsearch import exceptions
from app.core.config import settings

logger = logging.getLogger(__name__)


class ElasticsearchService:
    """Service for querying Elasticsearch logs."""
    
    def __init__(self):
        self.es_url = settings.es_url
        self.index_pattern = settings.es_index
        self.client: Optional[AsyncElasticsearch] = None
        
    async def connect(self):
        """Initialize Elasticsearch client."""
        if self.client is None:
            auth = None
            if settings.es_user and settings.es_password:
                auth = (settings.es_user, settings.es_password)
            
            self.client = AsyncElasticsearch(
                [self.es_url],
                basic_auth=auth,
                verify_certs=settings.es_verify_certs,
                request_timeout=30
            )
            logger.info(f"Connected to Elasticsearch: {self.es_url}")
    
    async def close(self):
        """Close Elasticsearch client."""
        if self.client:
            await self.client.close()
            self.client = None
    
    async def health_check(self) -> bool:
        """Check Elasticsearch connection health."""
        try:
            await self.connect()
            info = await self.client.info()
            logger.info(f"Elasticsearch cluster: {info['cluster_name']}")
            return True
        except Exception as e:
            logger.error(f"Elasticsearch health check failed: {e}")
            return False
    
    async def query_errors(
        self,
        app_name: Optional[str] = None,
        namespace: Optional[str] = None,
        level_min: int = 40000,  # ERROR level
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
        size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Query error logs from Elasticsearch.
        
        Args:
            app_name: Filter by application name
            namespace: Filter by Kubernetes namespace
            level_min: Minimum log level (40000 = ERROR)
            time_from: Start time (default: 20 minutes ago)
            time_to: End time (default: now)
            size: Maximum number of results
            
        Returns:
            List of log entries
        """
        await self.connect()
        
        if time_from is None:
            time_from = datetime.utcnow() - timedelta(minutes=20)
        if time_to is None:
            time_to = datetime.utcnow()
        
        # Build query
        must_conditions = [
            {"range": {"@timestamp": {"gte": time_from.isoformat(), "lte": time_to.isoformat()}}},
            {"range": {"level_value": {"gte": level_min}}}
        ]
        
        if app_name:
            must_conditions.append({"term": {"kubernetes.labels.app": app_name}})
        
        if namespace:
            must_conditions.append({"term": {"kubernetes.namespace_name": namespace}})
        
        query = {
            "query": {
                "bool": {
                    "must": must_conditions
                }
            },
            "size": size,
            "sort": [{"@timestamp": {"order": "desc"}}]
        }
        
        try:
            response = await self.client.search(
                index=self.index_pattern,
                body=query
            )
            
            hits = response["hits"]["hits"]
            logger.info(f"Found {len(hits)} error logs")
            
            return [hit["_source"] for hit in hits]
            
        except exceptions.ApiError as e:
            logger.error(f"Elasticsearch query failed: {e}")
            return []
    
    async def aggregate_errors(
        self,
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
        group_by_fields: List[str] = None
    ) -> Dict[str, Any]:
        """
        Aggregate error logs by fingerprint/app/namespace.
        
        Args:
            time_from: Start time
            time_to: End time
            group_by_fields: Fields to group by (default: app, namespace, normalized_message)
            
        Returns:
            Aggregated results with counts
        """
        await self.connect()
        
        if time_from is None:
            time_from = datetime.utcnow() - timedelta(minutes=20)
        if time_to is None:
            time_to = datetime.utcnow()
        
        if group_by_fields is None:
            group_by_fields = ["kubernetes.labels.app", "kubernetes.namespace_name"]
        
        # Build aggregation query
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": time_from.isoformat(), "lte": time_to.isoformat()}}},
                        {"range": {"level_value": {"gte": 40000}}}
                    ]
                }
            },
            "size": 0,
            "aggs": {
                "errors_by_app": {
                    "terms": {
                        "field": "kubernetes.labels.app.keyword",
                        "size": 50
                    },
                    "aggs": {
                        "by_namespace": {
                            "terms": {
                                "field": "kubernetes.namespace_name.keyword",
                                "size": 10
                            }
                        }
                    }
                }
            }
        }
        
        try:
            response = await self.client.search(
                index=self.index_pattern,
                body=query
            )
            
            return response["aggregations"]
            
        except exceptions.ApiError as e:
            logger.error(f"Elasticsearch aggregation failed: {e}")
            return {}
    
    async def get_similar_logs(
        self,
        message: str,
        app_name: str,
        time_window_hours: int = 24,
        size: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find similar log messages using Elasticsearch fuzzy search.
        
        Args:
            message: Log message to match
            app_name: Application name
            time_window_hours: Time window to search (hours)
            size: Number of results
            
        Returns:
            List of similar log entries
        """
        await self.connect()
        
        time_from = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"kubernetes.labels.app": app_name}},
                        {"range": {"@timestamp": {"gte": time_from.isoformat()}}}
                    ],
                    "should": [
                        {"match": {"message": {"query": message, "fuzziness": "AUTO"}}}
                    ],
                    "minimum_should_match": 1
                }
            },
            "size": size
        }
        
        try:
            response = await self.client.search(
                index=self.index_pattern,
                body=query
            )
            
            return [hit["_source"] for hit in response["hits"]["hits"]]
            
        except exceptions.ApiError as e:
            logger.error(f"Similar logs search failed: {e}")
            return []


# Singleton instance
es_service = ElasticsearchService()
