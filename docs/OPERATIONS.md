# Provoz — AI Log Analyzer

Vše co SRE/ops potřebuje pro běžný provoz, ladění a rozšíření systému.

---

## Obsah

1. [CronJob scheduling](#cronjob-scheduling)
2. [Alerting tuning](#alerting-tuning)
3. [Přidání nové aplikace / namespace](#přidání-nové-aplikace--namespace)
4. [Přidání application.version](#přidání-applicationversion)
5. [Přepočet thresholdů](#přepočet-thresholdů)
6. [Manuální operace](#manuální-operace)
7. [Testing schedule](#testing-schedule)
8. [Deployment checklist](#deployment-checklist)

---

## CronJob scheduling

### Přehled jobů

| CronJob | Schedule | Popis | Duration |
|---------|----------|-------|----------|
| `ai-log-analyzer-regular` | `*/15 * * * *` | Hlavní pipeline: fetch → detect → alert | 1-5 min |
| `ai-log-analyzer-backfill` | `0 2 * * *` | Denní backfill předchozího dne | 10-60 min |
| `ai-log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP z peak_raw_data | 1-5 min |

### Pořadí závislostí

```
backfill (2:00) → plní peak_raw_data
    │
    ├─ regular phase (*/15) → čte P93/CAP z DB, plní peak_raw_data
    │
    └─ thresholds (neděle 3:00) → čte peak_raw_data, přepočítá P93/CAP
```

### Regular Phase CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-regular
  namespace: ai-log-analyzer
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: regular
            image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
            command: ["python3", "scripts/regular_phase.py", "--quiet"]
            resources:
              requests: { memory: "1Gi", cpu: "500m" }
              limits: { memory: "2Gi", cpu: "1000m" }
          restartPolicy: OnFailure
          backoffLimit: 2
  successfulJobsHistoryLimit: 5
  failedJobsHistoryLimit: 3
```

### Backfill CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-backfill
  namespace: ai-log-analyzer
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backfill
            image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
            command: ["python3", "scripts/backfill.py", "--days", "1"]
            resources:
              requests: { memory: "2Gi", cpu: "1000m" }
              limits: { memory: "4Gi", cpu: "2000m" }
          restartPolicy: OnFailure
          backoffLimit: 3
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
```

### Threshold CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-thresholds
  namespace: ai-log-analyzer
spec:
  schedule: "0 3 * * 0"  # Neděle 03:00 UTC
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: thresholds
            image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest
            command: ["python3", "scripts/core/calculate_peak_thresholds.py", "--weeks", "4"]
          restartPolicy: OnFailure
```

---

## Alerting tuning

### Doporučený profil (SIT/UAT)

Profil pro snížení spamu při zachování signálu o nových nebo eskalujících problémech:

| Proměnná | Hodnota | Popis |
|----------|---------|-------|
| `MAX_PEAK_ALERTS_PER_WINDOW` | 3 | Max peaků v jednom digest emailu |
| `ALERT_DIGEST_ENABLED` | true | Digest místo jednotlivých emailů |
| `ALERT_COOLDOWN_MIN` | 45 | Min. interval mezi alerty pro stejný peak |
| `ALERT_HEARTBEAT_MIN` | 120 | Opakovaný alert pro pokračující peak |
| `ALERT_MIN_DELTA_PCT` | 30 | Min. změna error_count pro znovu-odeslání |
| `ALERT_CONTINUATION_LOOKBACK_MIN` | 60 | Lookback pro pokračující peak |

### Chování

- Jeden digest email za 15min okno (pokud jsou alerty k odeslání)
- Pokračující peak bez materiální změny se potlačí
- Znovu se posílá při: změně trendu, změně error_count ≥ `ALERT_MIN_DELTA_PCT`, nové aplikaci/namespace, heartbeat intervalu

### Rychlý tuning

**Méně emailů:**
- Zvýšit `ALERT_COOLDOWN_MIN` na 60–90
- Zvýšit `ALERT_MIN_DELTA_PCT` na 40–50
- Zvýšit `ALERT_HEARTBEAT_MIN` na 180

**Více citlivé alerty:**
- Snížit `ALERT_COOLDOWN_MIN` na 30
- Snížit `ALERT_MIN_DELTA_PCT` na 20
- Snížit `ALERT_HEARTBEAT_MIN` na 60

**Fallback na per-peak emaily:** `ALERT_DIGEST_ENABLED=false`

---

## Přidání nové aplikace / namespace

### 1. Přidat namespace do monitoringu

```yaml
# config/namespaces.yaml
namespaces:
  - pcb-dev-01-app
  - pcb-sit-01-app
  - nova-app-01-app    # ← přidat
```

### 2. Naplnit historická data

```bash
# Backfill pro nový namespace (14+ dní)
python3 scripts/backfill.py --days 14 --workers 4

# Přepočítat thresholdy
python3 scripts/core/calculate_peak_thresholds.py --weeks 3
```

### 3. Ověřit

```bash
python3 scripts/core/peak_detection.py --show-thresholds
# Zkontrolovat, že nový namespace má P93/CAP hodnoty
```

> **Poznámka:** Pro nový namespace bez P93/CAP dat použije PeakDetector fallback `default_threshold` (100).

---

## Přidání application.version

Pro detekci regresí po deployi je potřeba mít `application.version` v ES logech.

### 1. DB migrace

```sql
ALTER TABLE ailog_peak.peak_investigation
ADD COLUMN application_version VARCHAR(50);

CREATE INDEX idx_peak_inv_app_version
ON ailog_peak.peak_investigation(namespace, application_version);
```

### 2. ES query — přidat do `_source`

```python
# fetch_unlimited.py
"_source": [
    "timestamp", "namespace", "message",
    "application.version",  # ← přidat
]
```

### 3. Pipeline — uložit verzi

V `regular_phase.py` / `backfill.py` přidat verzi do INSERT do `peak_investigation`.

### 4. Výsledek

Incident Analysis automaticky:
- Detekuje `version_change_detected`
- Zobrazí v FACTS: `⚠️ VERSION CHANGE: order-service (1.8.3 → 1.8.4)`
- Upraví IMMEDIATE ACTIONS: `Review recent deployment`

---

## Přepočet thresholdů

### Automatický (CronJob)

Běží každou neděli 03:00 UTC. Žádná akce potřeba.

### Manuální

```bash
# Přepočítat z posledních 4 týdnů
python3 scripts/core/calculate_peak_thresholds.py --weeks 4

# Dry-run (jen zobrazí, neuloží)
python3 scripts/core/calculate_peak_thresholds.py --weeks 4 --dry-run

# Zobrazit aktuální thresholdy z DB
python3 scripts/core/peak_detection.py --show-thresholds
```

### Po backfillu

Vždy po manuálním backfillu přepočítat:
```bash
python3 scripts/backfill.py --days 14 --workers 4
python3 scripts/core/calculate_peak_thresholds.py --weeks 4
```

---

## Manuální operace

### Ad-hoc backfill

```bash
# Doplnit konkrétní období
python3 scripts/backfill.py --from "2026-02-01" --to "2026-02-14" --workers 4
```

### Dry-run regular phase

```bash
python3 scripts/regular_phase.py --window 15 --dry-run
```

### Test Teams notifikace

```python
from core.teams_notifier import TeamsNotifier
notifier = TeamsNotifier()
notifier.send_backfill_completed(
    days_processed=1, successful_days=1, failed_days=0,
    total_incidents=100, saved_count=100,
    registry_updates={'problems': 5, 'peaks': 1}, duration_minutes=5.5
)
```

### Test Confluence

```bash
python3 scripts/confluence_publisher.py \
  --page-id 1334314201 \
  --csv-file ./scripts/exports/errors_table_latest.csv \
  --title "Test: Known Errors"
```

---

## Testing schedule

Před deployem do produkce:

```bash
# 1. Test backfill (dry-run)
python3 scripts/backfill.py --days 1 --dry-run

# 2. Test regular phase
python3 scripts/regular_phase.py --window 15 --dry-run

# 3. Test P93/CAP thresholds
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose

# 4. Zobrazit thresholdy
python3 scripts/core/peak_detection.py --show-thresholds

# 5. Test Confluence connection
python3 scripts/confluence_publisher.py --page-id ... --csv-file ... --title "Test"
```

---

## Deployment checklist

- [ ] Backfill testován lokálně (1 den)
- [ ] Regular phase testován (15 min okno)
- [ ] P93/CAP thresholds naplněny
- [ ] PeakDetector ověřen (`--show-thresholds`)
- [ ] Teams webhook ověřen
- [ ] Confluence credentials ověřeny
- [ ] K8s manifesty vytvořeny / aktualizovány
- [ ] Resource limits nastaveny
- [ ] Monitoring/alerting setup
- [ ] Backup strategie (registry YAML)
