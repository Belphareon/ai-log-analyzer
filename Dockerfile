# ============================================================================
# AI Log Analyzer - Docker Image
# ============================================================================
# Build:
#   docker build -t dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag> .
#
# Push:
#   docker push dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>
#
# Run (local test):
#   docker run --env-file .env dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>
# ============================================================================

FROM python:3.11-slim

# Labels
LABEL maintainer="ai-log-analyzer-team"
LABEL description="AI Log Analyzer - peak detection, alerting, Confluence reporting"

# Set working directory
WORKDIR /app

# Install system dependencies (none required for binary wheels)

# Copy requirements and pre-downloaded wheels (for offline install)
COPY requirements.txt .
COPY wheels/ /wheels/

# Install Python dependencies (offline)
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# Copy application code
COPY scripts/ scripts/
COPY incident_analysis/ incident_analysis/
COPY config/ config/
COPY run_*.sh ./

# Compatibility symlink for legacy paths
RUN ln -s /app/scripts /scripts

# Make scripts executable
RUN chmod +x run_*.sh

# Create data directories
RUN mkdir -p data/batches data/reports data/snapshots

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/scripts

# Default command
CMD ["python", "scripts/regular_phase.py", "--quiet"]
