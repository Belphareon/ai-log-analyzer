# AI Log Analyzer - Deployment Guide

**Version:** 1.0  
**Last Updated:** 2025-11-12

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Database Setup](#database-setup)
6. [Running the Application](#running-the-application)
7. [Testing](#testing)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

- **Python 3.11+** - Main runtime
- **PostgreSQL 14+** - Database for patterns and findings
- **Elasticsearch 8.x** - Log source (read-only access)
- **Poetry** (recommended) or pip - Dependency management

### Optional Software

- **Docker/Podman** - For containerized deployment
- **Redis 7+** - For caching (future)
- **Ollama** - For local LLM (can use mock instead)

### System Requirements

- **RAM:** 2GB minimum, 4GB recommended
- **Disk:** 1GB for application, 5GB+ for PostgreSQL
- **Network:** Access to Elasticsearch cluster

---

## Quick Start

For the impatient - get Phase 1 (data analysis) running in 5 minutes:

```bash
# 1. Clone repository
cd ~/git/sas
git clone <repo-url> ai-log-analyzer
cd ai-log-analyzer

# 2. Install minimal dependencies for Phase 1
pip3 install --user elasticsearch httpx

# 3. Fetch errors from Elasticsearch
python3 fetch_errors.py \
  --from "2025-11-10T00:00:00" \
  --to "2025-11-10T23:59:59" \
  --max-sample 30000 \
  --output /tmp/daily_errors.json

# 4. Analyze and generate report
python3 analyze_daily.py \
  --input /tmp/daily_errors.json \
  --output /tmp/error_report.md

# 5. View report
cat /tmp/error_report.md
```

**That's it!** You now have ML-based error analysis without any database setup.

For full API deployment (Phase 2), continue reading.

---

## Installation

### Option 1: Poetry (Recommended)

```bash
cd ~/git/sas/ai-log-analyzer

# Install Poetry if not present
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Option 2: pip with requirements.txt

```bash
cd ~/git/sas/ai-log-analyzer

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Option 3: System-wide installation

```bash
cd ~/git/sas/ai-log-analyzer

# Install from pyproject.toml
pip3 install --user -e .
```

### Verify Installation

```bash
# Test imports
python3 -c "
from app.services.pattern_detector import pattern_detector
from app.services.llm_mock import MockLLMService
print('✅ Core components loaded successfully')
"

# Test Phase 1 scripts
python3 analyze_daily.py --help
```

---

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Application
APP_NAME=ai-log-analyzer
APP_ENV=development
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/ai_log_analyzer

# Elasticsearch
ES_URL=https://logs.example.com:9200
ES_USER=your_es_user
ES_PASSWORD=your_es_password
ES_INDEX_PATTERN=logstash-*

# LLM (Ollama)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama2
USE_MOCK_LLM=true  # Set to false when Ollama is ready

# EWMA Settings
EWMA_ALPHA=0.3
EWMA_THRESHOLD=2.0

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
```

### Elasticsearch Credentials

Get your ES credentials:

```bash
# For KB environment, credentials are in your .env
echo $ES_USER
echo $ES_PASSWORD
```

---

## Database Setup

### Install PostgreSQL

#### Ubuntu/Debian:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

#### Using Docker/Podman:
```bash
podman run -d \
  --name ai-log-analyzer-db \
  -e POSTGRES_USER=ailog \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=ai_log_analyzer \
  -p 5432:5432 \
  postgres:14
```

### Create Database

```bash
# Connect to PostgreSQL
sudo -u postgres psql

# Create user and database
CREATE USER ailog WITH PASSWORD 'your_password';
CREATE DATABASE ai_log_analyzer OWNER ailog;
GRANT ALL PRIVILEGES ON DATABASE ai_log_analyzer TO ailog;
\q
```

### Run Migrations

```bash
cd ~/git/sas/ai-log-analyzer

# Initialize Alembic (if not done)
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade -> b62720445820, initial schema with all models
INFO  [alembic.runtime.migration] Running upgrade b62720445820 -> ab4f703145e2, add foreign keys
INFO  [alembic.runtime.migration] Running upgrade ab4f703145e2 -> 1a266d9a61fb, add analyzed_at column
```

### Verify Database

```bash
# Check tables were created
psql -U ailog -d ai_log_analyzer -c "\dt"
```

Expected tables:
- `findings`
- `patterns`
- `feedback`
- `analysis_history`
- `ewma_baselines`
- `finding_patterns`

---

## Running the Application

### Phase 1: Standalone Scripts (No Database)

Phase 1 scripts work independently without any database:

```bash
# 1. Fetch errors from Elasticsearch
python3 fetch_errors.py \
  --from "2025-11-12T00:00:00" \
  --to "2025-11-12T23:59:59" \
  --max-sample 30000 \
  --output /tmp/daily_errors.json

# 2. Analyze and generate report
python3 analyze_daily.py \
  --input /tmp/daily_errors.json \
  --output /tmp/error_report.md

# 3. View results
cat /tmp/error_report.md
```

**Note:** These scripts are production-ready and currently in use!

---

## Docker Compose Deployment

### Start All Services

```bash
cd ~/git/sas/ai-log-analyzer

# Start all services (postgres, ollama, redis)
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### Initialize Database

```bash
# Run migrations after first start
docker-compose exec postgres psql -U ailog -d ailog_analyzer -c "\dt"

# Or run migrations from host
cd ~/git/sas/ai-log-analyzer
alembic upgrade head
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes all data!)
docker-compose down -v
```

---

## Testing

### Test Phase 1 Components

```bash
# Test pattern detector imports
python3 -c "
from app.services.pattern_detector import pattern_detector
print('✅ PatternDetector import OK')
"

# Test pattern normalization
python3 -c "
from app.services.pattern_detector import pattern_detector
msg1 = 'Card 12345 not found'
msg2 = 'Card 67890 not found'
norm1 = pattern_detector.normalize_message(msg1)
norm2 = pattern_detector.normalize_message(msg2)
print(f'✅ Normalization: {norm1 == norm2}')
"

# Test analyze_daily.py
python3 analyze_daily.py --help
```

### Test Phase 2 Components (Requires Dependencies)

```bash
# Install dependencies first
poetry install

# Test database models
python3 -c "
from app.models import Finding, Pattern, Feedback
print('✅ Models import OK')
"

# Test API server startup
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Troubleshooting

### "ModuleNotFoundError" for Phase 1

```bash
# Phase 1 scripts only need these
pip3 install --user elasticsearch httpx
```

### "ModuleNotFoundError" for Phase 2

```bash
# Install all dependencies
cd ~/git/sas/ai-log-analyzer
poetry install

# Or use pip
pip3 install -r requirements.txt
```

### Database Connection Failed

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check logs
docker-compose logs postgres

# Test connection
psql -U ailog -d ailog_analyzer -h localhost -p 5432
```

### Elasticsearch Connection Issues

```bash
# Verify credentials
echo $ES_USER
echo $ES_PASSWORD

# Test connection
curl -u "$ES_USER:$ES_PASSWORD" "$ES_URL/_cluster/health"
```

### Docker Compose Errors

```bash
# Restart all services
docker-compose restart

# Full reset (⚠️ deletes data)
docker-compose down -v
docker-compose up -d
```

---

## Next Steps

After successful deployment:

1. ✅ **Run Phase 1** - Generate daily error reports
2. 🚧 **Setup Phase 2** - Install dependencies, run migrations
3. 📊 **Integrate AWX** - Schedule daily analysis jobs
4. 🔄 **Monitor** - Track analysis quality over time

See [README.md](README.md) for detailed usage and [PROJECT_STATUS.md](PROJECT_STATUS.md) for development roadmap.

