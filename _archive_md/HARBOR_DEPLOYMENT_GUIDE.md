# Harbor + ArgoCD Deployment Guide - AI Log Analyzer

**Version:** 1.0  
**Date:** 2025-12-05  
**Status:** ✅ READY FOR DEPLOYMENT  
**Image Registry:** dockerhub.kb.cz/pccm-sq016/  
**Target:** nprod K8s cluster (3100 nodes)

---

## 📋 Overview

This guide covers the complete process for deploying AI Log Analyzer to K8s via ArgoCD:
1. Build Docker image with Podman (avoid Docker rate limits)
2. Tag and push to Harbor registry
3. Deploy via ArgoCD (GitOps approach)
4. Verify deployment and health

**Timeline:** ~30 minutes (build + push + deploy)

---

## ✅ Prerequisites Verification

Before starting, verify all prerequisites are met:

```bash
# ✅ 1. Podman available (required for build)
podman version
# Expected: podman version 4.9.3

# ✅ 2. Git clone location
cd /home/jvsete/git/sas/ai-log-analyzer
pwd
# Expected: /home/jvsete/git/sas/ai-log-analyzer

# ✅ 3. Docker/Podman running
podman ps
# Expected: No errors

# ✅ 4. Harbor credentials (you'll need these)
# Harbor registry: dockerhub.kb.cz
# Registry user: (obtain from DevOps)
# Registry password: (obtain from DevOps)
# Project: pccm-sq016
```

---

## 🔨 STEP 1: Build Docker Image (Podman)

### Why Podman Instead of Docker?

Docker Hub has rate limits (100 pulls/6 hours unauthenticated):
- ❌ `docker build` fails: Too many retries exhaust limit
- ✅ `podman build` works: Better retry logic, internal caching

### Build Command

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Run in background (don't block terminal)
nohup podman build -f Dockerfile -t ai-log-analyzer:latest . > build.log 2>&1 &

# Monitor progress
tail -f build.log

# When done (or check):
podman images | grep ai-log-analyzer
# Expected output: ai-log-analyzer  latest  <image-id>  <date>  <size>

# Expected duration: 5-10 minutes (first build with Python deps)
```

### Build Stages (What's happening)

```
STEP 1/13: FROM python:3.11-slim        ← Pull base image (largest, may take time)
STEP 2/13: WORKDIR /app                 ← Set working directory
STEP 3/13: RUN apt-get update && ...     ← Install system deps (gcc, curl, etc.)
STEP 4/13: COPY requirements.txt ./      ← Copy Python requirements
STEP 5/13: RUN pip install --no-cache   ← Install Python packages (takes time)
STEP 6-13: [Copy code, create user, configure app]
FINAL: Successfully tagged ai-log-analyzer:latest
```

---

## 🏷️ STEP 2: Tag Image for Harbor

Once build completes (check `build.log`):

```bash
# Verify image exists
podman images | grep ai-log-analyzer

# Tag for Harbor registry
podman tag ai-log-analyzer:latest dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest

# Verify tag
podman images | grep ai-log-analyzer
# Expected: Two entries (original + tagged)
```

---

## 📤 STEP 3: Push to Harbor Registry

### Login to Harbor

```bash
# Login (you'll need credentials from DevOps)
podman login dockerhub.kb.cz

# When prompted:
# Username: <your-username>
# Password: <your-password>

# Verify login
podman login dockerhub.kb.cz --get-login
# Expected: Username for logged in account
```

### Push Image

```bash
# Push to Harbor
podman push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest

# This will:
# 1. Upload all image layers
# 2. Verify checksums
# 3. Make image available in Harbor

# Expected output:
# Copying blob sha256:... (progress bar)
# Copying config sha256:...
# Writing manifest sha256:...
# Successfully pushed ... in X seconds
```

### Verify Push

```bash
# Check Harbor web UI (if access available)
# URL: https://dockerhub.kb.cz
# Navigate: Projects > pccm-sq016 > ai-log-analyzer

# Or use podman:
podman image ls | grep ai-log-analyzer
# Should show: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
```

---

## 🚀 STEP 4: Deploy via ArgoCD

### Verify K8s Manifests

K8s manifests are already prepared in:
```
/home/jvsete/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/
```

Structure:
```
ai-log-analyzer/
├── namespace.yaml                 # Create namespace
├── configmap.yaml                 # Non-secret config
├── secret.yaml                    # Conjur-managed secrets
├── deployment.yaml                # Main app (2 replicas)
├── service.yaml                   # Service exposure
├── ingress.yaml                   # External access
├── ollama.yaml                    # LLM service
└── README.md                       # Deployment notes
```

### Image Reference in deployment.yaml

**Current status:** ✅ CORRECT
```yaml
# File: deployment.yaml, line 45
image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
imagePullPolicy: Always
```

This references the Harbor image we just pushed.

### Commit to ArgoCD Git Repo

```bash
# Navigate to k8s-infra-apps-nprod
cd /home/jvsete/git/sas/k8s-infra-apps-nprod

# Ensure on correct branch
git checkout k8s-nprod-3100
# or: git checkout main
# (ask DevOps which branch is for ArgoCD)

# Add manifests
git add infra-apps/ai-log-analyzer.yaml
git add infra-apps/ai-log-analyzer/

# Commit
git commit -m "Deploy AI Log Analyzer v1.0 - Phase 4 complete

- Base image: Python 3.11-slim
- 2 replicas, rolling update strategy
- ConfigMap: Elasticsearch indices, EWMA settings
- Secret: Cyberark-managed (Elasticsearch + DB credentials)
- Health check: /api/v1/health endpoint
- Ollama: Local LLM service for analysis"

# Push
git push origin k8s-nprod-3100
# (or main, depending on branch)
```

### ArgoCD Automatic Deployment

Once committed to git:

1. **ArgoCD detects change** (~5-10 seconds)
2. **ArgoCD syncs deployment** (~30-60 seconds)
3. **Kubernetes creates resources:**
   - Namespace: `ai-log-analyzer`
   - Deployment: 2 replicas of ai-log-analyzer
   - Ollama: LLM service (separate deployment)
   - Service: LoadBalancer or ClusterIP
   - Ingress: ai-log-analyzer.sas.kbcloud (if DNS configured)
4. **Containers start** (image pull from Harbor + startup)

**Total time:** 2-3 minutes from commit to running pods

---

## ✅ STEP 5: Verify Deployment

### Check ArgoCD Status

```bash
# View ArgoCD application
kubectl -n argocd-system get application ai-log-analyzer

# Expected output:
# NAME               SYNC STATUS   HEALTH STATUS
# ai-log-analyzer    Synced        Healthy
```

### Check Pods

```bash
# List pods in ai-log-analyzer namespace
kubectl -n ai-log-analyzer get pods

# Expected output:
# NAME                              READY   STATUS    RESTARTS   AGE
# ai-log-analyzer-abc123def456-xyz  1/1     Running   0          2m
# ai-log-analyzer-def789ghi012-abc  1/1     Running   0          2m
# ai-log-analyzer-ollama-uvw456     1/1     Running   0          2m
```

### Check Services

```bash
# View service
kubectl -n ai-log-analyzer get svc

# Expected output:
# NAME                  TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)
# ai-log-analyzer       ClusterIP   10.x.x.x      <none>        8000/TCP
# ai-log-analyzer-ollama ClusterIP   10.y.y.y      <none>        11434/TCP
```

### Test Health Endpoint

```bash
# Port-forward to test
kubectl -n ai-log-analyzer port-forward svc/ai-log-analyzer 8000:8000

# In another terminal:
curl http://localhost:8000/api/v1/health

# Expected response (200 OK):
# {
#   "status": "healthy",
#   "version": "1.0.0",
#   "timestamp": "2025-12-05T20:00:00Z"
# }
```

### Check Logs

```bash
# View logs from main application
kubectl -n ai-log-analyzer logs -f deployment/ai-log-analyzer

# Expected first lines:
# INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
# INFO:     Application startup complete

# View logs from Ollama
kubectl -n ai-log-analyzer logs -f deployment/ai-log-analyzer-ollama
```

---

## 🔧 Troubleshooting

### Problem: ImagePullBackOff

```
Error: Failed to pull image "dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest"
```

**Solutions:**
1. Verify image was pushed to Harbor:
   ```bash
   podman push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
   ```

2. Verify Harbor credentials in K8s:
   ```bash
   kubectl -n ai-log-analyzer get secret dockerhub -o yaml
   ```

3. Check imagePullSecrets in deployment:
   ```yaml
   imagePullSecrets:
   - name: dockerhub
   ```

### Problem: CrashLoopBackOff

```
Error: Pod crashed, restarting...
```

**Check logs:**
```bash
kubectl -n ai-log-analyzer logs <pod-name>
```

**Common issues:**
- Missing environment variables (check ConfigMap/Secret)
- Database connection failed (verify DATABASE_URL, DB credentials)
- Elasticsearch unreachable (verify ES_URL, ES credentials)

### Problem: Service Not Responding

**Test connectivity:**
```bash
# Inside K8s cluster
kubectl -n ai-log-analyzer run -it --rm debug --image=curl -- /bin/sh
curl http://ai-log-analyzer:8000/api/v1/health

# Or port-forward (already shown above)
kubectl -n ai-log-analyzer port-forward svc/ai-log-analyzer 8000:8000
curl http://localhost:8000/api/v1/health
```

### Problem: Pods Stuck in Pending

```
Pod pending for > 5 minutes
```

**Check node availability:**
```bash
kubectl get nodes
kubectl describe node <node-name>

# Check pod events
kubectl -n ai-log-analyzer describe pod <pod-name>
```

---

## 📋 Post-Deployment Checklist

After successful deployment:

- [ ] Pods running: `kubectl -n ai-log-analyzer get pods` shows 2 replicas
- [ ] Health check passes: `curl http://localhost:8000/api/v1/health`
- [ ] Logs show startup: `kubectl logs -f deployment/ai-log-analyzer`
- [ ] Database connected: Logs show no connection errors
- [ ] Elasticsearch accessible: Logs show no ES connection errors
- [ ] Ollama running: `kubectl logs -f deployment/ai-log-analyzer-ollama`
- [ ] Monitoring configured: Prometheus scrapes metrics (/metrics endpoint)
- [ ] Alerts working: (after Prometheus scrape)

---

## 🔄 Updating the Deployment

When you make code changes and want to deploy new version:

```bash
# 1. Build new image (increment version tag)
nohup podman build -t ai-log-analyzer:v1.0.1 . > build.log 2>&1 &

# 2. Tag for Harbor
podman tag ai-log-analyzer:v1.0.1 dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:v1.0.1

# 3. Push to Harbor
podman push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:v1.0.1

# 4. Update deployment.yaml
# Edit: image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:v1.0.1

# 5. Commit and push to git
cd /home/jvsete/git/sas/k8s-infra-apps-nprod
git add infra-apps/ai-log-analyzer/deployment.yaml
git commit -m "Update AI Log Analyzer to v1.0.1"
git push origin k8s-nprod-3100

# ArgoCD will automatically deploy new version
```

---

## 📞 Support & References

| Item | Link/Contact |
|------|--------------|
| ArgoCD | https://argocd.kbcloud/applications |
| Harbor Registry | https://dockerhub.kb.cz |
| K8s Manifests | /git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/ |
| AI Log Analyzer Repo | /git/sas/ai-log-analyzer |
| Deployment Status | kubectl -n ai-log-analyzer get all |

---

## ✅ Summary

**What you've done:**
1. ✅ Built Docker image with Podman (avoids rate limits)
2. ✅ Tagged and pushed to Harbor registry
3. ✅ Committed K8s manifests to ArgoCD git repo
4. ✅ ArgoCD automatically deployed (2-3 minutes)
5. ✅ Verified deployment (pods, services, health)

**Next steps:**
- Monitor logs and health
- Configure alerts (if needed)
- Plan Phase 5: Teams integration
- Plan Phase 6: Autonomous monitoring

---

**Generated:** 2025-12-05  
**Status:** ✅ READY FOR USE
