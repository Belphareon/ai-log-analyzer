"""Services initialization."""
import logging
from app.services.llm_mock import mock_llm_service

logger = logging.getLogger(__name__)

# Try to import real Ollama service, fallback to mock
try:
    from app.services.llm import ollama_service
    # Use mock for now due to network issues
    llm_service = mock_llm_service
    logger.info("Using Mock LLM service (Ollama unavailable)")
except Exception as e:
    from app.services.llm_mock import mock_llm_service
    llm_service = mock_llm_service
    logger.warning(f"Failed to import Ollama service, using mock: {e}")

__all__ = ["llm_service"]
