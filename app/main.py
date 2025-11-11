"""
AI Log Analyzer - Main FastAPI application.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import engine, Base
from app.api import analyze, feedback, health, logs, trends

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(
    title="AI Log Analyzer",
    description="Intelligent log analysis with self-learning capabilities",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analyze.router, prefix="/api/v1", tags=["analyze"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(logs.router, prefix="/api/v1", tags=["logs"])
app.include_router(trends.router, prefix="/api/v1", tags=["trends"])


@app.on_event("startup")
async def startup_event():
    """Startup tasks."""
    logger.info("AI Log Analyzer starting up...")
    logger.info(f"Database: {settings.database_url}")
    logger.info(f"Ollama: {settings.ollama_url}")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown tasks."""
    logger.info("AI Log Analyzer shutting down...")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "AI Log Analyzer",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
