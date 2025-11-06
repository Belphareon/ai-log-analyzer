"""API endpoints for Elasticsearch log queries."""
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from app.services.elasticsearch import es_service

router = APIRouter(prefix="/logs", tags=["logs"])


class LogEntry(BaseModel):
    """Log entry response model."""
    timestamp: str
    app_name: Optional[str] = None
    namespace: Optional[str] = None
    level: str
    message: str
    container: Optional[str] = None


class ErrorsResponse(BaseModel):
    """Response for error logs query."""
    total: int
    logs: List[dict]
    time_from: str
    time_to: str


@router.get("/errors", response_model=ErrorsResponse)
async def query_errors(
    app_name: Optional[str] = Query(None, description="Filter by application name"),
    namespace: Optional[str] = Query(None, description="Filter by Kubernetes namespace"),
    minutes: int = Query(20, description="Time window in minutes", ge=1, le=1440),
    size: int = Query(100, description="Maximum number of results", ge=1, le=1000)
):
    """
    Query error logs from Elasticsearch.
    
    Returns errors from the specified time window, grouped by application and namespace.
    """
    time_to = datetime.utcnow()
    time_from = time_to - timedelta(minutes=minutes)
    
    try:
        logs = await es_service.query_errors(
            app_name=app_name,
            namespace=namespace,
            time_from=time_from,
            time_to=time_to,
            size=size
        )
        
        return ErrorsResponse(
            total=len(logs),
            logs=logs,
            time_from=time_from.isoformat(),
            time_to=time_to.isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")


@router.get("/aggregations")
async def get_error_aggregations(
    minutes: int = Query(20, description="Time window in minutes", ge=1, le=1440)
):
    """
    Get aggregated error statistics by app and namespace.
    
    Returns counts grouped by application and namespace.
    """
    time_to = datetime.utcnow()
    time_from = time_to - timedelta(minutes=minutes)
    
    try:
        aggs = await es_service.aggregate_errors(
            time_from=time_from,
            time_to=time_to
        )
        
        return {
            "time_from": time_from.isoformat(),
            "time_to": time_to.isoformat(),
            "aggregations": aggs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to aggregate logs: {str(e)}")


@router.get("/similar")
async def find_similar_logs(
    message: str = Query(..., description="Log message to match"),
    app_name: str = Query(..., description="Application name"),
    hours: int = Query(24, description="Time window in hours", ge=1, le=168),
    size: int = Query(5, description="Number of similar logs", ge=1, le=20)
):
    """
    Find similar log messages using fuzzy matching.
    
    Useful for finding related incidents or recurring issues.
    """
    try:
        similar = await es_service.get_similar_logs(
            message=message,
            app_name=app_name,
            time_window_hours=hours,
            size=size
        )
        
        return {
            "query": message,
            "app_name": app_name,
            "time_window_hours": hours,
            "similar_logs": similar,
            "count": len(similar)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find similar logs: {str(e)}")


@router.get("/health")
async def elasticsearch_health():
    """Check Elasticsearch connection health."""
    is_healthy = await es_service.health_check()
    
    if is_healthy:
        return {"status": "healthy", "elasticsearch": "connected"}
    else:
        raise HTTPException(status_code=503, detail="Elasticsearch is not available")
