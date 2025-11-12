# Kubernetes Deployment Manifests

This directory contains Kubernetes deployment manifests for AI Log Analyzer.

## Files

- `deployment.yaml` - Main application deployment
- `service.yaml` - Service exposure
- `configmap.yaml` - Non-sensitive configuration
- `secret.yaml.template` - Template for secrets (DO NOT commit actual secrets)
- `ingress.yaml` - Ingress rules (optional)

## Files

- `namespace.yaml` - Namespace definition
- `deployment.yaml` - Main application deployment
- `service.yaml` - Service exposure
- `configmap.yaml` - Non-sensitive configuration
- `secret.yaml.template` - Template for secrets (DO NOT commit actual secrets)
- `ingress.yaml` - Ingress rules (optional)

## Quick Deploy

```bash
# 1. Create namespace
kubectl apply -f namespace.yaml

# 2. Create secret from template
cp secret.yaml.template secret.yaml
# Edit secret.yaml with your actual credentials
kubectl apply -f secret.yaml

# 3. Apply all manifests
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# 4. Optional: Apply ingress (edit host first)
kubectl apply -f ingress.yaml

# 5. Verify deployment
kubectl get pods -n ai-log-analyzer
kubectl get svc -n ai-log-analyzer

# 6. Check logs
kubectl logs -f deployment/ai-log-analyzer -n ai-log-analyzer

# 7. Test health
kubectl port-forward svc/ai-log-analyzer 8000:8000 -n ai-log-analyzer
curl http://localhost:8000/api/v1/health
```

## Prerequisites

Before deploying, ensure you have:

1. **Database:** PostgreSQL accessible from cluster
2. **Elasticsearch:** ES cluster accessible
3. **LLM Service:** Ollama or OpenAI API access
4. **Container Image:** Build and push image first

## Building Container Image

```bash
# Build image
docker build -t your-registry/ai-log-analyzer:latest .

# Push to registry
docker push your-registry/ai-log-analyzer:latest

# Update deployment.yaml with your image
```

## Environment Variables

See `secret.yaml.template` and `configmap.yaml` for required variables.

---

*Created: 2025-11-12*
