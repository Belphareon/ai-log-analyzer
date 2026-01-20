# ============================================================================
# AI Log Analyzer - Docker Image
# ============================================================================
# Build:
#   docker build -t ai-log-analyzer:latest .
#
# Run:
#   docker run --env-file .env ai-log-analyzer:latest python scripts/regular_phase.py
# ============================================================================

FROM python:3.11-slim

# Labels
LABEL maintainer="your-team@company.com"
LABEL version="4.0"
LABEL description="AI Log Analyzer - Incident Detection Pipeline"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scripts/ scripts/
COPY config/ config/
COPY run_*.sh ./

# Make scripts executable
RUN chmod +x run_*.sh

# Create data directories
RUN mkdir -p data/batches data/reports data/snapshots

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/scripts

# Default command
CMD ["python", "scripts/regular_phase.py", "--quiet"]
