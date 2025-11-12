"""
Analysis endpoint - main AI analysis API.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import logging

from app.core.database import get_db
from app.schemas import FindingAnalysisRequest, FindingAnalysisResponse
from app.services import llm_service as ollama_service
from app.services.prompts import format_analyze_prompt, SYSTEM_PROMPT
from app.models import Finding
from app.services.analyzer import analyzer_service
from app.services.elasticsearch import es_service
import json
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger(__name__)

# Level value mapping
LEVEL_VALUES = {
    "DEBUG": 0,
    "INFO": 1,
    "WARN": 2,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
    "FATAL": 4,
}


@router.post("/analyze", response_model=List[FindingAnalysisResponse])
async def analyze_findings(
    request: FindingAnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    Analyze log findings with AI.
    
    - Performs root cause analysis
    - Provides recommendations
    - Matches against known patterns
    - Finds similar incidents
    """
    try:
        results = []
        
        for finding_data in request.findings:
            # Check if finding already exists
            existing = db.query(Finding).filter(
                Finding.fingerprint == finding_data.fingerprint
            ).first()
            
            if existing:
                # Update count and last_seen
                existing.count += finding_data.count
                existing.last_seen = datetime.utcnow()
                finding = existing
            else:
                # Create new finding
                finding = Finding(
                    fingerprint=finding_data.fingerprint,
                    app_name=finding_data.app_name,
                    namespace=finding_data.namespace,
                    container=finding_data.container,
                    message=finding_data.message,
                    normalized_message=finding_data.normalized_message or finding_data.message,  # Default to message if not provided
                    stack_trace=finding_data.stack_trace,
                    level=finding_data.level,
                    level_value=finding_data.level_value or LEVEL_VALUES.get(finding_data.level.upper(), 1),
                    count=finding_data.count,
                    context_data=finding_data.context_data,
                )
                db.add(finding)
            
            # Extract trace details from context_data
            trace_id = None
            span_id = None
            pod_name = None
            timestamp = None
            
            if finding_data.context_data:
                trace_id = finding_data.context_data.get("traceId")
                span_id = finding_data.context_data.get("spanId")
                pod_name = finding_data.context_data.get("pod")
                timestamp = finding_data.context_data.get("timestamp")
            
            # Prepare context for AI
            context = request.context.get("additional_info", "")
            similar_incidents = ""
            related_logs = ""
            
            # If we have traceId, fetch related logs from ES
            if trace_id:
                try:
                    # Query ES for logs with same traceId to get full context
                    from elasticsearch import AsyncElasticsearch
                    await es_service.connect()
                    
                    # Search for all logs with this traceId (not just errors)
                    trace_query = {
                        "query": {
                            "bool": {
                                "must": [
                                    {"term": {"traceId.keyword": trace_id}},
                                    {"range": {"@timestamp": {
                                        "gte": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                                        "lte": datetime.utcnow().isoformat()
                                    }}}
                                ]
                            }
                        },
                        "size": 20,
                        "sort": [{"@timestamp": {"order": "asc"}}]
                    }
                    
                    response = await es_service.client.search(
                        index=es_service.index_pattern,
                        body=trace_query
                    )
                    
                    trace_logs = [hit["_source"] for hit in response["hits"]["hits"]]
                    
                    if trace_logs:
                        # Find the most detailed error message (usually contains ErrorModel, exception details)
                        most_detailed_error = None
                        max_detail_score = 0
                        
                        for log in trace_logs:
                            msg = log.get('message', '')
                            detail_score = 0
                            
                            # Score based on detail indicators
                            if 'ErrorModel' in msg or 'Exception' in msg:
                                detail_score += 10
                            if 'code=' in msg or 'err.' in msg:
                                detail_score += 5
                            if 'uuid=' in msg:
                                detail_score += 3
                            if 'detail=' in msg or 'Detail:' in msg:
                                detail_score += 5
                            if len(msg) > 200:  # Longer messages often have more detail
                                detail_score += 2
                            
                            if detail_score > max_detail_score and log.get('level') == 'ERROR':
                                max_detail_score = detail_score
                                most_detailed_error = log
                        
                        # Build related logs output with most detailed error first
                        related_logs_list = []
                        if most_detailed_error:
                            related_logs_list.append(
                                f"[PRIMARY ERROR] {most_detailed_error.get('logger_name', '')}: {most_detailed_error.get('message', '')}"
                            )
                        
                        # Add other logs for context
                        for log in trace_logs[:10]:
                            if log != most_detailed_error:
                                related_logs_list.append(
                                    f"[{log.get('level', 'INFO')}] {log.get('@timestamp', '')} - {log.get('logger_name', '')}: {log.get('message', '')[:150]}"
                                )
                        
                        related_logs = "\n".join(related_logs_list)
                        logger.info(f"Found {len(trace_logs)} related logs for traceId {trace_id}, most detailed error score: {max_detail_score}")
                
                except Exception as e:
                    logger.warning(f"Failed to fetch related logs for traceId {trace_id}: {e}")
            
            if request.include_similar:
                # Find similar past findings
                similar = db.query(Finding).filter(
                    Finding.app_name == finding_data.app_name,
                    Finding.fingerprint != finding_data.fingerprint
                ).limit(3).all()
                
                if similar:
                    similar_incidents = "\n".join([
                        f"- {s.message[:100]} (resolved: {s.resolved})"
                        for s in similar
                    ])
            
            # Generate AI analysis
            prompt = format_analyze_prompt(
                app_name=finding_data.app_name,
                namespace=finding_data.namespace,
                error_message=finding_data.message,
                count=finding_data.count,
                stack_trace=finding_data.stack_trace,
                context=context,
                similar_incidents=similar_incidents,
                trace_id=trace_id,
                span_id=span_id,
                pod_name=pod_name,
                timestamp=timestamp,
                related_logs=related_logs
            )
            
            try:
                ai_response = await ollama_service.generate(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=1000
                )
                
                # Parse JSON response
                response_text = ai_response.get("response", "{}")
                try:
                    analysis = json.loads(response_text)
                except json.JSONDecodeError:
                    # Fallback if not valid JSON
                    analysis = {
                        "root_cause": response_text[:500],
                        "recommendations": [],
                        "confidence": 50,
                        "severity": "medium"
                    }
                
                # Update finding with analysis
                finding.root_cause = analysis.get("root_cause")
                finding.recommendations = analysis.get("recommendations", [])
                finding.confidence = analysis.get("confidence")
                finding.severity = analysis.get("severity")
                finding.analysis_timestamp = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"AI analysis failed: {e}")
                # Continue without AI analysis
                analysis = {}
            
            db.commit()
            db.refresh(finding)
            
            # Build response
            primary_rec = analysis.get("primary_recommendation")
            results.append(FindingAnalysisResponse(
                fingerprint=finding.fingerprint,
                app_name=finding.app_name,
                namespace=finding.namespace,
                message=finding.message,
                count=finding.count,
                root_cause=finding.root_cause,
                primary_recommendation=primary_rec,
                recommendations=finding.recommendations,
                confidence=finding.confidence,
                severity=finding.severity,
                trace_analysis=analysis.get("trace_analysis"),
                similar_incidents=[{"id": s.id, "message": s.message[:100]} for s in (similar if request.include_similar else [])],
                matched_patterns=[],
                context_data={
                    "traceId": trace_id,
                    "spanId": span_id,
                    "pod": pod_name,
                    "timestamp": timestamp,
                    "related_logs_count": len(related_logs.split("\n")) if related_logs else 0
                },
                analysis_timestamp=finding.analysis_timestamp or datetime.utcnow(),
                finding_id=finding.id
            ))
        
        return results
        
    except Exception as e:
        logger.error(f"Analysis endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
