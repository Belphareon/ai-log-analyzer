# AI Log Analyzer

Intelligent log analysis agent with self-learning capabilities for AWX logwatch integration.

## Features

- 🤖 **Local LLM Analysis** - Uses Ollama (Mistral/Llama3) for intelligent log analysis
- 📊 **Pattern Recognition** - Automatically learns from historical findings
- 🎯 **Self-Learning** - Adjusts thresholds and filters based on feedback
- 🔍 **Context Enhancement** - Correlates with Elasticsearch, ArgoCD deployments
- 💡 **Smart Recommendations** - Suggests root causes and remediation steps

## Architecture

```
AWX Logwatch → AI Agent API → Ollama LLM → PostgreSQL
                    ↓
            Enhanced Findings + Insights
```

## Components

- **API Server** (FastAPI) - REST endpoints for AWX integration
- **Analyzer** - Core LLM-based log analysis
- **Learner** - Pattern recognition and auto-adjustment
- **Context Provider** - Elasticsearch and ArgoCD integration
- **Database** - PostgreSQL for findings history and learned patterns

## Tech Stack

- Python 3.11+
- FastAPI (async API)
- Ollama (local LLM)
- PostgreSQL (data persistence)
- SQLAlchemy (ORM)
- Kubernetes (deployment)

## Project Structure

```
ai-log-analyzer/
├── app/
│   ├── api/              # FastAPI endpoints
│   ├── core/             # Core analyzer logic
│   ├── models/           # SQLAlchemy models
│   ├── services/         # Business logic
│   │   ├── analyzer.py   # Main analysis engine
│   │   ├── learner.py    # Self-learning module
│   │   ├── llm.py        # Ollama client
│   │   └── context.py    # ES/ArgoCD integration
│   ├── schemas/          # Pydantic schemas
│   └── utils/            # Helpers
├── k8s/                  # Kubernetes manifests
├── tests/                # Unit tests
├── docker-compose.yml    # Local development
├── Dockerfile            # Container image
├── pyproject.toml        # Poetry dependencies
└── README.md
```

## Quick Start

### Local Development

```bash
# Install dependencies
poetry install

# Start services (PostgreSQL, Ollama)
docker-compose up -d

# Run migrations
poetry run alembic upgrade head

# Start API server
poetry run uvicorn app.main:app --reload
```

### API Usage

```bash
# Analyze findings
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d @findings.json

# Get learned patterns
curl http://localhost:8000/api/v1/patterns

# Submit feedback
curl -X POST http://localhost:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"finding_id": "123", "is_valid": true}'
```

## Configuration

Environment variables:
- `DATABASE_URL` - PostgreSQL connection string
- `OLLAMA_URL` - Ollama API endpoint
- `OLLAMA_MODEL` - Model to use (mistral, llama3)
- `ES_URL` - Elasticsearch endpoint
- `ES_INDEX` - Log index pattern

## Development Roadmap

- [x] Project setup
- [ ] Core analyzer with Ollama
- [ ] PostgreSQL schema and models
- [ ] REST API endpoints
- [ ] Self-learning module
- [ ] Elasticsearch integration
- [ ] Kubernetes deployment
- [ ] AWX integration

## License

Internal KB use only
