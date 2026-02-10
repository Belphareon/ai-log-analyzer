# ============================================================================
# AI Log Analyzer - Docker Image
# ============================================================================
# Build:
#   docker build -t ai-log-analyzer:r8 .
#
# Run:
#   docker run --env-file .env ai-log-analyzer:r8 python scripts/regular_phase_v6.py
# ============================================================================

FROM python:3.11-slim

# Labels
LABEL maintainer="your-team@company.com"
LABEL version="6.0.4"
LABEL description="AI Log Analyzer - Incident Detection Pipeline"

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
COPY core/ core/
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
CMD ["python", "scripts/regular_phase_v6.py", "--quiet"]
