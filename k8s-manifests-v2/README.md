# AI Log Analyzer - K8s Manifests (Phase 4 - Minimal)

**Version:** 2.0  
**Date:** 2025-12-05  
**Status:** ✅ READY FOR DEPLOYMENT  
**Changes from v1.0:** Removed Ollama, cleaned ConfigMap, updated deployment

---

## �� What's Changed (v1.0 → v2.0)

### Removed
- ❌ `ollama.yaml` - Not needed for Phase 4, requires 20GB storage, no image in Harbor
- ❌ Ollama references from ConfigMap
- ❌ PersistentVolumeClaim for Ollama data

### Updated
- ✅ `deployment.yaml` - Removed Ollama service references, reduced resource requests
- ✅ `configmap.yaml` - Removed Ollama hardcoded URL, kept localhost fallback
- ✅ `secret.yaml` - Simplified, added TODO notes for NPROD verification
- ✅ All manifests - Consistent labeling, namespacing, proper RBAC prep

### Simplified
- Service account: Using `default` (TODO: create `ai-log-analyzer` service account later)
- Resource limits: Reduced from 2Gi/1000m to 1Gi/500m (more realistic)
- Environment: Cleaner, commented for clarity

---

## 📁 Files

| File | Purpose | Deploy |
|------|---------|--------|
| `00-namespace.yaml` | Create namespace | ✅ ALWAYS |
| `01-configmap.yaml` | App configuration (non-secrets) | ✅ ALWAYS |
| `02-secret.yaml` | Credentials (Cyberark refs) | ✅ ALWAYS |
| `03-service.yaml` | Expose port 8000 | ✅ ALWAYS |
| `04-deployment.yaml` | Main app (2 replicas) | ✅ ALWAYS |
| `05-ingress.yaml` | External DNS access | ⚠️ OPTIONAL |

**Total:** 5 core manifests + 1 optional

---

## 🚀 Deployment

### Prerequisites

1. **Docker image built and pushed:**
   ```bash
   podman build -t ai-log-analyzer:latest .
   podman tag ... dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
   podman push ...
   ```

2. **Harbor credentials available** in K8s:
   ```bash
   kubectl create secret docker-registry dockerhub \
     --docker-server=dockerhub.kb.cz \
     --docker-username=<user> \
     --docker-password=<pass> \
     --namespace=ai-log-analyzer
   ```
   (Usually pre-configured by cluster admin)

3. **Database prepared:**
   - Database: `ailog_analyzer` on `P050TD01.DEV.KB.CZ`
   - User: `ailog_analyzer_user_d1` (already created)
   - Cyberark credentials in safe: `DAP_PCB`

4. **Elasticsearch accessible:**
   - URL: `elasticsearch-test.kb.cz:9500`
   - Credentials in Cyberark (already tested ✓)

### Deploy to K8s

**Via ArgoCD (GitOps - Recommended):**
```bash
# 1. Copy manifests to k8s-infra-apps-nprod repo
cp -r /path/to/k8s-manifests-v2/* \
  /path/to/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/

# 2. Commit
cd /path/to/k8s-infra-apps-nprod
git add infra-apps/ai-log-analyzer/
git commit -m "Update AI Log Analyzer manifests v2.0 (Phase 4 - minimal)"
git push

# 3. ArgoCD auto-deploys
```

**Manually (for testing only):**
```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-configmap.yaml
kubectl apply -f 02-secret.yaml
kubectl apply -f 03-service.yaml
kubectl apply -f 04-deployment.yaml
# kubectl apply -f 05-ingress.yaml  # Optional, if DNS ready
```

---

## ✅ Verification

### Check Deployment
```bash
kubectl -n ai-log-analyzer get all

# Expected:
# NAMESPACE NAME                                    READY   STATUS
# ai-log-analyzer deployment.apps/ai-log-analyzer  2/2     Running
```

### Check Pods
```bash
kubectl -n ai-log-analyzer get pods

# Expected: 2 running replicas
# ai-log-analyzer-5d8f7c4b6d-xyz   1/1  Running  0  2m
# ai-log-analyzer-5d8f7c4b6d-abc   1/1  Running  0  2m
```

### Check Logs
```bash
kubectl -n ai-log-analyzer logs -f deployment/ai-log-analyzer

# Expected: Uvicorn startup, no errors
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

### Test Health
```bash
# Port-forward
kubectl -n ai-log-analyzer port-forward svc/ai-log-analyzer 8000:8000

# Test endpoint
curl http://localhost:8000/api/v1/health

# Expected: 200 OK with health status
```

### Test Database Connection
```bash
kubectl -n ai-log-analyzer logs deployment/ai-log-analyzer | grep -i database

# Expected: No "ERROR" or "connection refused" messages
# Should show: "Database initialized" or similar
```

### Test Elasticsearch Connection
```bash
kubectl -n ai-log-analyzer logs deployment/ai-log-analyzer | grep -i elasticsearch

# Expected: No connection errors
# Should show: "Connected to Elasticsearch" or indices query results
```

---

## ⚠️ TODOs Before Production

### Must-Do
- [ ] Replace `P050TD01.DEV.KB.CZ` with actual NPROD database host (if different)
- [ ] Verify Cyberark credential paths exist and are accessible
- [ ] Test Harbor image pull (may need credentials configured by admin)
- [ ] Confirm all ConfigMap values match your environment

### Should-Do
- [ ] Create dedicated `ai-log-analyzer` service account + RBAC
- [ ] Configure Prometheus scraping (already annotated in Deployment)
- [ ] Set up alerting rules for pod crashes, high CPU/memory
- [ ] Enable Ingress (if DNS ready) or configure port-forward for external access

### Nice-to-Have
- [ ] Add HorizontalPodAutoscaler for auto-scaling
- [ ] Add NetworkPolicy for security
- [ ] Add PodDisruptionBudget for availability

---

## 🔧 Troubleshooting

### ImagePullBackOff
```
Events: Failed to pull image dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
```

**Fix:**
1. Verify image was pushed to Harbor
2. Confirm Harbor credentials in K8s (`dockerhub` secret)
3. Check image exists: `podman images` on builder machine

### CrashLoopBackOff
```
Container exited with code 1
```

**Check:**
```bash
kubectl logs <pod-name>
```

Common issues:
- Missing DATABASE_URL (check env substitution)
- Elasticsearch unreachable (check ES_URL)
- Database connection failed (check credentials, host)

### Pods Pending
```
Pod status: Pending for > 5 minutes
```

**Check:**
```bash
kubectl describe pod <pod-name>
kubectl describe node <node-name>
```

Look for:
- Insufficient resources (memory, CPU)
- Volume binding issues
- Pod anti-affinity failures

---

## 📞 Support

| Issue | Reference |
|-------|-----------|
| Docker image build | See `/repo/HARBOR_DEPLOYMENT_GUIDE.md` |
| K8s deployment | See `/repo/DEPLOYMENT.md` |
| Database setup | See `/repo/scripts/setup/init_ailog_peak_schema.py` |
| Elasticsearch connection | See `/repo/scripts/test/test_es_connection.py` |

---

## 📊 Manifest Summary

```
00-namespace.yaml        10 lines  ✅ Essential
01-configmap.yaml        31 lines  ✅ Essential  
02-secret.yaml           20 lines  ✅ Essential
03-service.yaml          18 lines  ✅ Essential
04-deployment.yaml      130 lines  ✅ Essential
05-ingress.yaml          20 lines  ⚠️ Optional
---
Total                   229 lines
```

---

**Generated:** 2025-12-05  
**Status:** ✅ READY FOR USE  
**Next Step:** Build & push Docker image, then deploy via ArgoCD
