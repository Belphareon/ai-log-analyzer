# Troubleshooting - AI Log Analyzer

## r111: DB Runtime And Reporting

The deployed nprod PostgreSQL mode supersedes the legacy filesystem recovery examples below. Never fix a missing DB checkpoint by deleting registry files, clearing `runtime_state`, rerunning bootstrap over existing state, or switching to the old PVC image: these actions can lose known fingerprints or replay delivered alerts. Use [the operations guide](OPERATIONS.md#r111-runtime-bez-pvc) for a controlled handoff or rollback.

| Symptom | Check And Action |
|---------|------------------|
| Collector Pending / `FailedAttachVolume` | Verify its actual image and pod volumes. r111 regular in `postgres` mode has only `emptyDir`; a PVC mount means a legacy/stale workload or wrong backend. Do not delete the PVC, Cinder reservation or attachment finalizers. |
| `runtime state is not seeded` | Check migration 013, init bootstrap result and query scope. Missing or stale `report_knowledge` requires explicit import, not an empty fallback. Bootstrap never overwrites an existing checkpoint. |
| `another runtime state writer is active` | Locate the current scoped scheduled/manual collector and let it finish; do not disable the lease. A PostgreSQL session close releases it. |
| Direct regular invocation rejects missing writer lease | Use the configured `--scheduled` workflow; no unleased `postgres` fallback is supported. |
| Handoff failed and regular remains suspended | This is deliberate fail-closed behavior. Resolve the specific init/quiesce failure and repeat the complete sync; do not resume the old filesystem writer against a seeded DB. |
| Argo says hook prerequisites succeeded but Job has `FailedCreate: serviceaccount ... not found` | Verify the actual ServiceAccount/Role/RoleBinding and current operation results. The r111 incident recovered by terminating only the blocked Argo operation and starting a fresh official full sync, without force/replace/prune. Underlying km helper cause was not investigated. Core CLI mode needs the Argo namespace in the selected context; avoid changing the user's active kubeconfig. |
| Confluence HTTP 413 | Check `confluence_request_prepared.request_bytes` and image version. Bound tables/preface and the 4MiB serialized UTF-8 request guard prevent the observed 5MiB rejection; repeating the same oversized payload is not a fix. The historical peak catalog must use the same bounds. |
| Report uploaded but `daily_complete=false` | Check 96-window coverage, reconciliation and `pending_window_count`. Partial publication is allowed; daily Teams/email remains gated. Missing windows are not zero-error windows and historical catch-up does not replay alerts. |

Report tables display at most 100 rows and 192 characters per cell, with explicit truncation notices; the daily preface has its own 128 Ki-character limit. Full DB facts and pod-local CSV are not truncated, but CSV files are neither durable backups nor automatically published attachments. A refused PUT is not recorded as successful delivery. State persistence does not provide exactly-once external delivery across a crash between provider acceptance and DB commit.

## Časté problémy a řešení

### 1. Reporty se negenerují

**Symptom:** Adresář `scripts/reports/` je prázdný.

**Příčina (v5.3):** Podmínka `total_incidents > 0` blokovala generaci.

**Řešení (v5.3.1):** Aktualizujte na v5.3.1 - report se generuje VŽDY.

```bash
# Ověření
ls -la scripts/reports/

# Měl by existovat soubor i při 0 incidentech:
# incident_analysis_15min_20260123_091500.txt
```

### 2. AttributeError: 'IncidentScope' object has no attribute 'propagated'

**Symptom:**
```
AttributeError: 'IncidentScope' object has no attribute 'propagated'
```

**Příčina:** Používáte starý kód který očekává `scope.propagated`.

**Řešení (v5.3.1):** Propagation je nyní samostatný objekt:

```python
# PŘED (v5.3 - špatně)
incident.scope.propagated

# PO (v5.3.1 - správně)
incident.propagation.propagated
```

Aktualizujte na v5.3.1.

### 3. Registry se neaktualizuje

**Symptom:** `registry/known_errors.yaml` zůstává prázdný nebo neaktuální.

**Kontrola:**
```bash
# Oprávnění
ls -la registry/
# Mělo by být zapisovatelné

# Logy
python scripts/regular_phase.py 2>&1 | grep -i "registry"
```

**Řešení:**
```bash
# Vytvořit adresář s oprávněními
mkdir -p registry
chmod 755 registry
```

### 4. ModuleNotFoundError: No module named 'incident_analysis'

**Symptom:**
```
ModuleNotFoundError: No module named 'incident_analysis'
```

**Řešení:**
```bash
# Přidat do PYTHONPATH
export PYTHONPATH=/path/to/ai-log-analyzer:$PYTHONPATH

# Nebo spouštět z root adresáře
cd /path/to/ai-log-analyzer
python scripts/regular_phase.py
```

### 5. Import chyba: IncidentPropagation

**Symptom:**
```
ImportError: cannot import name 'IncidentPropagation' from 'incident_analysis'
```

**Příčina:** Stará verze modulu.

**Řešení:** Aktualizujte na v5.3.1:
```bash
# Nahradit soubory
cp -r new_version/incident_analysis/* incident_analysis/

# Ověřit
python -c "from incident_analysis import IncidentPropagation; print('OK')"
```

### 6. Prázdné incidenty i když jsou errory

**Symptom:** Errory v ES existují, ale analýza vrací 0 incidentů.

**Kontrola:**
```bash
# Verbose mode
python scripts/regular_phase.py 2>&1 | head -50
```

**Možné příčiny:**
1. Errory nesplňují threshold pro peak detection
2. Časové okno je mimo rozsah dat
3. Namespace filter je příliš restriktivní

### 7. DB connection timeout

**Symptom:**
```
psycopg2.OperationalError: connection timed out
```

**Řešení:**
```bash
# Zkontrolovat .env
cat config/.env | grep DB_

# Test připojení
python -c "
import psycopg2
conn = psycopg2.connect(
    host='$DB_HOST',
    port=5432,
    database='$DB_NAME',
    user='$DB_USER',
    password='$DB_PASSWORD',
    connect_timeout=10
)
print('OK')
"
```

### 8. YAML parse error v registry

**Symptom:**
```
yaml.scanner.ScannerError: ...
```

**Příčina:** Poškozený YAML soubor.

**Řešení:**
```bash
# Backup a reset
mv registry/known_errors.yaml registry/known_errors.yaml.bak
echo "[]" > registry/known_errors.yaml

# Validace YAML
python -c "import yaml; yaml.safe_load(open('registry/known_errors.yaml'))"
```

### 9. Cron nefunguje

**Symptom:** Cron job běží, ale žádný output.

**Kontrola:**
```bash
# Cron log
grep ai-log /var/log/cron

# Manual test s cron prostředím
env -i /bin/bash -c 'cd /path/to && python scripts/regular_phase.py'
```

**Typické příčiny:**
1. Špatná cesta
2. Chybějící PYTHONPATH
3. Chybějící .env

**Řešení - wrapper script:**
```bash
#!/bin/bash
# run_regular.sh
cd /opt/ai-log-analyzer
source venv/bin/activate
source config/.env
python scripts/regular_phase.py --quiet
```

### 10. Permission denied při zápisu

**Symptom:**
```
PermissionError: [Errno 13] Permission denied: 'scripts/reports/...'
```

**Řešení:**
```bash
# Opravit oprávnění
chmod -R 755 scripts/reports/
chmod -R 755 registry/

# Nebo změnit vlastníka
chown -R $USER:$USER scripts/reports/ registry/
```

## Diagnostický příkaz

```bash
# Kompletní diagnostika
python -c "
import sys
print('Python:', sys.version)

# Imports
try:
    from incident_analysis import (
        IncidentAnalysisEngine,
        IncidentPropagation,
        IncidentScope,
    )
    print('✅ Imports OK')
except ImportError as e:
    print('❌ Import error:', e)

# DB
try:
    import psycopg2
    print('✅ psycopg2 OK')
except:
    print('❌ psycopg2 missing')

# YAML
try:
    import yaml
    print('✅ yaml OK')
except:
    print('❌ yaml missing')

# Paths
from pathlib import Path
print('Reports dir exists:', Path('scripts/reports').exists())
print('Registry dir exists:', Path('registry').exists())
"
```

## Kontakt

Pro nevyřešené problémy kontaktujte Platform Engineering team.
