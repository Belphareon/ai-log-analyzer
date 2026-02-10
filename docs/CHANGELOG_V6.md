# AI Log Analyzer V6 - Opravy Registry a Detection

## Poslední aktualizace (10. února 2026)

### ✅ Nové v tomto updatu

| Komponenta | Změna | Commit |
|-----------|--------|--------|
| **PostgreSQL Transactions** | Přidán ROLLBACK exception handling | 5ad8904 |
| **Teams Notifications** | TEAMS_ENABLED env variable pro K8s | 8e1fbe4 |
| **K8s Deployment** | Přidán backfill CronJob (09:00 UTC) | bd5bad9 |
| **Docker Image** | Tag r4 s core/ a incident_analysis/ | local |
| **K8s Values** | Image tag r3→r4, všechny env vars | bd5bad9 |

### 🐛 Opravené bugy

| Bug | Root Cause | Řešení | Stav |
|-----|-----------|--------|------|
| Transaction abort cascade | Chybí ROLLBACK na exception | Added `conn.rollback()` | ✅ FIXED |
| Teams notifications silent | TEAMS_ENABLED not in K8s env | Added env variable | ✅ FIXED |
| PostgreSQL role permission | Expected behavior - user lacks grant | Documented as expected | ✅ HANDLED |

### 🚀 K8s Deployment Ready

- ✅ Two CronJobs deployed:
  - Regular Phase: `*/15 * * * *` (every 15 minutes)
  - Backfill Phase: `0 9 * * *` (09:00 UTC daily)
- ✅ Docker image r4 in registry (174 MB)
- ✅ All environment variables configured
- ✅ Teams notifications enabled
- ✅ Confluence integration ready (page 1334314207)

---

## Přehled problémů a oprav

### ❌ Původní problémy

| # | Problém | Dopad | Stav |
|---|---------|-------|------|
| 1a | Backfill opakovaně ukládá data pro stejné dny | Duplicity v DB | ✅ FIXED |
| 1b | Registry lookup nefunguje - vše je označeno jako NEW | 700k záznamů místo ~1k | ✅ FIXED |
| 2 | `Root cause: Unknown` u většiny errorů | Bez užitečné klasifikace | ✅ IMPROVED |
| 3 | known_peaks.yaml prázdné | Peaks se neukládají | ✅ FIXED |
| 4 | Chybí detail k errorům/peakům | Nedohledatelné | ✅ FIXED |
| 5 | Verze aplikace = "v1" (deployment label) | Špatná informace | ✅ FIXED |
| 6 | first_seen = last_seen | Timestamp běhu scriptu | ✅ FIXED |
| 7 | Duplicitní fingerprinty | Exploze registry | ✅ FIXED |
| 8 | Script neukončí po report | Visí bez exitu | ✅ FIXED |

---

## Nová architektura

### Dvouúrovňová identita problémů

```
┌─────────────────────────────────┐
│ PROBLEM REGISTRY (LIDSKÁ)       │  ← Málo záznamů, stabilní
│ - problem_key                   │
│ - first_seen / last_seen        │
│ - occurrences                   │
│ - scope / flow                  │
│ - jira / notes                  │
└─────────────▲───────────────────┘
              │ 1:N
┌─────────────┴───────────────────┐
│ FINGERPRINT INDEX (TECHNICKÝ)   │  ← Hodně záznamů
│ - fingerprint                   │
│ - problem_key (FK)              │
│ - sample_messages               │
└─────────────────────────────────┘
```

### Problem Key format

```
CATEGORY:flow:error_class

Příklady:
- BUSINESS:card_servicing:validation_error
- DATABASE:batch_processing:connection_pool
- AUTH:card_opening:access_denied
```

---

## Nové soubory

### Core moduly

| Soubor | Popis |
|--------|-------|
| `core/problem_registry.py` | Hlavní registry modul s problem_key |
| `pipeline/phase_c_detect.py` | Detection s registry integrací (V6) |

### Scripty

| Soubor | Popis |
|--------|-------|
| `backfill_v6.py` | Backfill s kompletní registry integrací |
| `regular_phase_v6.py` | 15-min pipeline s registry |
| `migrate_registry.py` | Migrace starého formátu registry |

---

## Jak upgradovat

### Krok 1: Analyzuj stávající registry

```bash
python migrate_registry.py --analyze --old-dir ./registry
```

Výstup ukáže:
- Počet existujících záznamů
- Distribuci kategorií
- Kolik problem_keys bude vytvořeno
- Detekci problematických timestampů

### Krok 2: Spusť migraci (dry-run)

```bash
python migrate_registry.py --dry-run --old-dir ./registry
```

Preview bez změn.

### Krok 3: Spusť migraci

```bash
python migrate_registry.py --old-dir ./registry --new-dir ./registry
```

Automaticky vytvoří backup.

### Krok 4: Použij nové scripty

```bash
# Backfill
python backfill_v6.py --days 14 --workers 4

# Regular phase (cron)
python regular_phase_v6.py
```

---

## Klíčové změny v chování

### 1. Registry se načítá před pipeline

**Předtím:**
```python
pipeline = PipelineV6()  # known_fingerprints = empty set
```

**Nyní:**
```python
registry = init_registry(registry_dir)
pipeline.phase_c.known_fingerprints = registry.get_all_known_fingerprints()
```

### 2. Event timestamps místo run timestamps

**Předtím:**
```python
entry['first_seen'] = datetime.now().isoformat()  # ❌ Čas scriptu
```

**Nyní:**
```python
entry.first_seen = min(entry.first_seen, incident.time.first_seen)  # ✅ Čas eventu
```

### 3. Problem_key místo 1:1 fingerprint

**Předtím:**
- Každá varianta message = nový záznam
- 700k záznamů po 20 dnech

**Nyní:**
- Podobné errory = jeden problem
- ~1k záznamů po 20 dnech

### 4. Peaks se ukládají

**Předtím:**
```python
# Detekce spike=2 v logu
# known_peaks.md zůstává prázdné
```

**Nyní:**
```python
if incident.flags.is_spike:
    registry._update_peak(incident, 'SPIKE', first_ts, last_ts)
```

### 5. Správné ukončení scriptu

**Předtím:**
- Script visí po "Report saved..."

**Nyní:**
```python
atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

---

## Nový formát registry souborů

### known_problems.yaml

```yaml
- id: KP-000001
  problem_key: BUSINESS:card_servicing:validation_error
  category: business
  flow: card_servicing
  error_class: validation_error
  first_seen: '2026-01-05T08:15:32Z'  # Z event timestamps!
  last_seen: '2026-01-26T10:32:51Z'
  occurrences: 15432
  fingerprints:
    - a02e513ec5e3f683
    - 26478f5bf03fb6b6
    - 9882fe300e44ed0e
  affected_apps:
    - bff-pcb-ch-card-servicing-v1
    - bl-pcb-client-rainbow-status-v1
  affected_namespaces:
    - pcb-dev-01-app
    - pcb-sit-01-app
    - pcb-uat-01-app
  deployments_seen:
    - bff-pcb-ch-card-servicing-v1
  app_versions_seen:
    - 4.65.2
    - 4.65.3
  scope: CROSS_NS  # LOCAL | CROSS_NS | SYSTEMIC
  status: OPEN
  jira: null
  notes: null
```

### known_peaks.yaml

```yaml
- id: PK-000001
  problem_key: PEAK:business:card_servicing:spike
  peak_type: SPIKE
  first_seen: '2026-01-20T14:30:00Z'
  last_seen: '2026-01-25T09:15:00Z'
  occurrences: 12
  fingerprints:
    - a02e513ec5e3f683
  affected_apps:
    - bl-pcb-v1
  affected_namespaces:
    - pcb-sit-01-app
  max_value: 125.4
  max_ratio: 8.5
  status: OPEN
  jira: null
  notes: null
```

### fingerprint_index.yaml

```yaml
BUSINESS:card_servicing:validation_error:
  - a02e513ec5e3f683
  - 26478f5bf03fb6b6
  - 9882fe300e44ed0e
  
DATABASE:batch_processing:connection_pool:
  - f4a8e9b2c3d5a1b7
```

---

## Doporučený deployment

### Kubernetes CronJob pro backfill

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: log-analyzer-backfill
spec:
  schedule: "0 2 * * 0"  # Neděle 2:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: analyzer
            image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r1
            command:
            - python
            - backfill_v6.py
            - --days
            - "7"
            - --workers
            - "4"
          restartPolicy: OnFailure
```

### Kubernetes CronJob pro regular phase

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: log-analyzer-regular
spec:
  schedule: "*/15 * * * *"  # Každých 15 minut
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: analyzer
            image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r1
            command:
            - python
            - regular_phase_v6.py
          restartPolicy: OnFailure
```

---

## Testování

### Dry-run backfill

```bash
python backfill_v6.py --days 3 --dry-run
```

Ověří:
- Registry se načte
- Data se zpracují
- Nic se neuloží do DB

### Forced re-processing

```bash
python backfill_v6.py --days 14 --force
```

Zpracuje i dny, které už jsou v DB (pro regeneraci s novými pravidly).

---

---

## V6.1 - Telemetry Context & Trace Propagation (2026-01-26)

### Nové funkce

#### 1. IncidentTelemetryContext

Jednotná normalizační vrstva pro ES eventy:

```python
@dataclass
class IncidentTelemetryContext:
    deployment_label: str                 # application.name (s -v1, -v2)
    application_version: Optional[str]    # POUZE X.Y.Z nebo None
    environment: Environment              # prod/uat/sit/dev
    trace_id: Optional[str]
    span_id: Optional[str]
    parent_span_id: Optional[str]
    event_timestamp: datetime
```

#### 2. Trace-based Propagation Detection

Detekce šíření incidentu přes více services pomocí traceId:

```python
# Agregace trace kontextů
trace_contexts = aggregate_trace_contexts(telemetry_contexts)

# Detekce propagace
propagation = detect_propagation(trace_contexts)

if propagation.propagated:
    print(f"Root service: {propagation.root_deployment}")
    print(f"Affected services: {propagation.affected_deployments}")
    print(f"Propagation time: {propagation.propagation_time_sec}s")
```

#### 3. Oddělené verze a deploymenty

| Pole | Zdroj | Příklad |
|------|-------|---------|
| `deployment_labels` | application.name | `my-app-v1`, `my-app-v2` |
| `app_versions` | application.version | `3.5.0`, `3.5.1` |

**ZAKÁZÁNO:**
- ❌ Extrakce verze z `-v1`, `-v2` suffixu
- ❌ Build number jako verze
- ❌ SDK/API version

#### 4. Rozšířené tabulkové exporty

Nové sloupce v CSV/MD/JSON exportech:

| Sloupec | Popis |
|---------|-------|
| `deployment_labels` | Deployment labels (app-v1, app-v2) |
| `app_versions` | Skutečné semantic verze (3.5.0) |

### Nové soubory

| Soubor | Popis |
|--------|-------|
| `core/telemetry_context.py` | Telemetry normalizační vrstva |
| `exports/table_exporter.py` | Tabulkové exporty (CSV, MD, JSON) |

### Upravené soubory

| Soubor | Změny |
|--------|-------|
| `pipeline/phase_a_parse.py` | Extrakce span_id, parent_span_id, environment |
| `pipeline/incident.py` | PropagationInfo, TraceInfo dataclasses |
| `core/problem_registry.py` | Ukládání app_versions_seen odděleně |

### Použití

```bash
# Export tabulek
python exports/table_exporter.py --registry ../registry --output ./exports

# Backfill s novými features
python backfill_v6.py --days 14 --workers 4
```

### CSV export ukázka

```csv
problem_id,category,flow,deployment_labels,app_versions,scope,status
KP-000001,business,card,svc-a-v1,3.5.0,CROSS_NS,OPEN
```

---

## Možná budoucí vylepšení

1. ~~**Verze aplikace** - Extrakce z ES pole `application.version`~~ ✅ DONE
2. ~~**Trace propagation** - Detekce šíření přes traceId~~ ✅ DONE
3. **XLSX export** - Pro lepší práci s daty
4. **Flow detection** - Automatická detekce business flows z call chain
5. **Trending** - Detekce trendů napříč dny

---

## Kontakt

Při problémech nebo dotazech kontaktuj tým SAS.
