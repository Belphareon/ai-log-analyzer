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
        
        # Detect error type
        if "nullpointerexception" in prompt_lower or "null" in prompt_lower:
            return {
                "root_cause": "Null pointer dereference - object was not initialized before use",
                "recommendations": [
                    "Add null checks before accessing object properties",
                    "Review object initialization in CardService constructor",
                    "Implement defensive programming with Optional/nullable handling"
                ],
                "confidence": 85,
                "severity": "high"
            }
        
        elif "outofmemory" in prompt_lower or "memory" in prompt_lower:
            return {
                "root_cause": "Memory exhaustion - heap space exceeded",
                "recommendations": [
                    "Increase JVM heap size (-Xmx parameter)",
                    "Review memory leaks in application",
                    "Implement pagination for large data sets"
                ],
                "confidence": 90,
                "severity": "critical"
            }
        
        elif "timeout" in prompt_lower or "connection" in prompt_lower:
            return {
                "root_cause": "Network connectivity issue or slow external service",
                "recommendations": [
                    "Increase connection timeout settings",
                    "Check network connectivity to external services",
                    "Implement circuit breaker pattern for resilience"
                ],
                "confidence": 75,
                "severity": "medium"
            }
        
        elif "database" in prompt_lower or "sql" in prompt_lower:
            return {
                "root_cause": "Database connection or query issue",
                "recommendations": [
                    "Check database connection pool settings",
                    "Review slow query logs",
                    "Verify database indexes are properly configured"
                ],
                "confidence": 80,
                "severity": "high"
            }
        
        else:
            # Generic error analysis
            return {
                "root_cause": "Application error - specific cause requires deeper investigation",
                "recommendations": [
                    "Review application logs for stack trace details",
                    "Check recent deployments or configuration changes",
                    "Monitor error frequency and patterns"
                ],
                "confidence": 60,
                "severity": "medium"
            }
    
    async def health_check(self) -> bool:
        """Mock health check always returns True."""
        return True
    
    async def list_models(self) -> list[str]:
        """Return list of mock models."""
        return ["mock-llm-v1"]


# Singleton instance
mock_llm_service = MockLLMService()
