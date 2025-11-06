"""
LLM Service for Ollama integration.
Provides interface for log analysis using local LLM models.
"""
import logging
from typing import Optional, Dict, Any
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class OllamaService:
    """Service for interacting with Ollama LLM."""
    
    def __init__(self):
        self.base_url = settings.ollama_url
        self.model = settings.ollama_model
        self.timeout = 120.0
        
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate response from Ollama.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional Ollama options
            
        Returns:
            Dict with response and metadata
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    }
                }
                
                if system_prompt:
                    payload["system"] = system_prompt
                    
                payload["options"].update(kwargs)
                
                logger.debug(f"Calling Ollama with model={self.model}, prompt_len={len(prompt)}")
                
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                
                logger.info(
                    f"LLM response received: {result.get('eval_count', 0)} tokens in "
                    f"{result.get('total_duration', 0) / 1e9:.2f}s"
                )
                
                return {
                    "response": result.get("response", ""),
                    "model": result.get("model"),
                    "created_at": result.get("created_at"),
                    "done": result.get("done"),
                    "total_duration": result.get("total_duration"),
                    "eval_count": result.get("eval_count"),
                }
                
        except httpx.TimeoutException as e:
            logger.error(f"Timeout calling Ollama: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Ollama: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            raise
    
    async def health_check(self) -> bool:
        """Check if Ollama is available and has models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    if models:
                        logger.info(f"Ollama healthy with {len(models)} models")
                        return True
                    else:
                        logger.warning("Ollama running but no models installed")
                        return False
                return False
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False
    
    async def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                return [m.get("name") for m in models]
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []


# Singleton instance
ollama_service = OllamaService()
