# AI Log Analyzer V6 - Opravy Registry a Detection

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
            image: your-registry/log-analyzer:v6
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
            image: your-registry/log-analyzer:v6
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

## Možná budoucí vylepšení

1. **XLSX export** - Pro lepší práci s daty
2. **Flow detection** - Automatická detekce business flows z call chain
3. **Verze aplikace** - Extrakce z ES pole `application.version`
4. **Root cause inference** - Lepší odvození root cause bez LLM
5. **Trending** - Detekce trendů napříč dny

---

## Kontakt

Při problémech nebo dotazech kontaktuj tým SAS.
