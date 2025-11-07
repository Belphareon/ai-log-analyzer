"""
Mock LLM Service for testing without actual LLM.
Returns structured responses for log analysis.
"""
import logging
import json
import hashlib
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MockLLMService:
    """Mock LLM service for testing."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate mock response based on prompt analysis.
        """
        self.logger.info(f"Mock LLM called with prompt length: {len(prompt)}")
        
        # Simple analysis based on keywords in prompt
        response = self._analyze_prompt(prompt)
        
        return {
            "response": json.dumps(response, indent=2),
            "model": "mock-llm-v1",
            "created_at": "2025-11-06T00:00:00Z",
            "done": True,
            "total_duration": 100000000,  # 0.1s in nanoseconds
            "eval_count": 50,
        }
    
    def _analyze_prompt(self, prompt: str) -> Dict[str, Any]:
        """Analyze prompt and return appropriate mock response."""
        prompt_lower = prompt.lower()
        
        # Extract trace info if present
        trace_analysis = "No trace information available"
        if "trace id:" in prompt_lower and "not available" not in prompt_lower:
            trace_analysis = "Trace analysis shows request flow through multiple services"
        
        # Extract specific error details from ErrorModel if present
        import re
        error_code = None
        resource_id = None
        error_message = None
        
        # Look for ErrorModel pattern: code=err.XXX, message=..., etc.
        code_match = re.search(r'code=(err\.\d+)', prompt, re.IGNORECASE)
        if code_match:
            error_code = code_match.group(1)
        
        # Look for resource IDs (card id, user id, etc.)
        id_match = re.search(r'(?:card|user|customer|account|product)\s+(?:with\s+)?id\s+(\d+)', prompt, re.IGNORECASE)
        if id_match:
            resource_id = id_match.group(1)
        
        # Extract error message from ErrorModel
        msg_match = re.search(r'message=([^,\]]+(?:not found[^,\]]*)?)', prompt, re.IGNORECASE)
        if msg_match:
            error_message = msg_match.group(1).strip()
        
        # If we have ErrorModel details, use them for precise analysis
        if error_code or (error_message and 'not found' in error_message.lower()):
            root_cause = f"API Error {error_code or 'err.103'}: {error_message or 'Resource not found'}"
            if resource_id:
                root_cause += f" (Resource ID: {resource_id})"
            
            return {
                "root_cause": root_cause,
                "recommendations": [
                    f"Verify that resource with ID {resource_id} exists in the database" if resource_id else "Verify resource exists in database",
                    "Check if resource was deleted or migrated to different system",
                    "Review data consistency between services (event-processor-relay → bl-pcb)",
                    "Add validation before attempting to fetch non-existent resources",
                    "Implement proper 404 handling with user-friendly error messages",
                    "Consider caching frequently accessed resources to reduce lookup failures"
                ],
                "confidence": 95,
                "severity": "medium",
                "trace_analysis": f"Trace shows request from bl-pcb-event-processor-relay to bl-pcb API. Error code: {error_code or 'err.103'}" if error_code else trace_analysis
            }
        
        # Detect error type from patterns
        if "nullpointerexception" in prompt_lower or "null" in prompt_lower:
            return {
                "root_cause": "Null pointer dereference - object was not initialized before use",
                "recommendations": [
                    "Add null checks before accessing object properties",
                    "Review object initialization in constructor",
                    "Implement defensive programming with Optional/nullable handling",
                    "Add unit tests to catch null pointer scenarios",
                    "Review recent code changes that might have introduced this issue"
                ],
                "confidence": 85,
                "severity": "high",
                "trace_analysis": trace_analysis
            }
        
        elif "outofmemory" in prompt_lower or "memory" in prompt_lower:
            return {
                "root_cause": "Memory exhaustion - heap space exceeded during operation",
                "recommendations": [
                    "Increase JVM heap size (-Xmx parameter)",
                    "Review memory leaks in application code",
                    "Implement pagination for large data sets",
                    "Add memory monitoring and alerts",
                    "Profile application to identify memory hotspots"
                ],
                "confidence": 90,
                "severity": "critical",
                "trace_analysis": trace_analysis
            }
        
        elif "404" in prompt_lower or "not found" in prompt_lower:
            return {
                "root_cause": "Resource not found - endpoint or entity does not exist at specified path",
                "recommendations": [
                    "Verify the requested resource ID exists in database",
                    "Check API endpoint routing configuration",
                    "Review recent API changes or migrations",
                    "Implement proper error handling for missing resources",
                    "Add logging to track what resources are being requested"
                ],
                "confidence": 80,
                "severity": "medium",
                "trace_analysis": trace_analysis
            }
        
        elif "timeout" in prompt_lower or "connection" in prompt_lower:
            return {
                "root_cause": "Network connectivity issue or slow external service response",
                "recommendations": [
                    "Increase connection timeout settings",
                    "Check network connectivity to external services",
                    "Implement circuit breaker pattern for resilience",
                    "Add retry logic with exponential backoff",
                    "Monitor external service health and SLA"
                ],
                "confidence": 75,
                "severity": "medium",
                "trace_analysis": trace_analysis
            }
        
        elif "database" in prompt_lower or "sql" in prompt_lower:
            return {
                "root_cause": "Database connection or query execution issue",
                "recommendations": [
                    "Check database connection pool settings",
                    "Review slow query logs for performance issues",
                    "Verify database indexes are properly configured",
                    "Monitor database resource utilization",
                    "Check for database locks or deadlocks"
                ],
                "confidence": 80,
                "severity": "high",
                "trace_analysis": trace_analysis
            }
        
        elif "readiness" in prompt_lower or "health" in prompt_lower:
            return {
                "root_cause": "Application readiness probe failure - service not ready to accept traffic",
                "recommendations": [
                    "Check application startup dependencies (DB, external services)",
                    "Review readiness probe configuration and timeout settings",
                    "Verify all required resources are available",
                    "Check application logs for startup errors",
                    "Increase readiness probe initial delay if needed"
                ],
                "confidence": 85,
                "severity": "high",
                "trace_analysis": trace_analysis
            }
        
        else:
            # Generic error analysis - check if we have trace info
            if "related logs" in prompt_lower and "no related logs" not in prompt_lower:
                trace_analysis = "Multiple log entries found in trace - investigate the sequence for root cause"
            
            return {
                "root_cause": "Application error - requires investigation of trace and related logs for specific cause",
                "recommendations": [
                    "Review complete trace logs for error context",
                    "Check recent deployments or configuration changes",
                    "Monitor error frequency and patterns over time",
                    "Investigate related services in the trace",
                    "Add additional logging if root cause is unclear"
                ],
                "confidence": 60,
                "severity": "medium",
                "trace_analysis": trace_analysis
            }
    
    async def health_check(self) -> bool:
        """Mock health check always returns True."""
        return True
    
    async def list_models(self) -> list[str]:
        """Return list of mock models."""
        return ["mock-llm-v1"]


# Singleton instance
mock_llm_service = MockLLMService()
