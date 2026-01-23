# AI Log Analyzer V4

**Deterministický incident detektor pro Elasticsearch logy**

Automaticky detekuje anomálie a incidenty v aplikačních logách. Místo jednoduchého "hodně errorů = problém" používá statistické metody (EWMA, MAD) pro přesnou detekci skutečných problémů vs. běžného šumu.

---

## 🎯 Jaký problém řeší?

| Problém | Běžný přístup | AI Log Analyzer V4 |
|---------|---------------|-------------------|
| **False positives** | Statický práh (>100 errors = alert) | Dynamický baseline per časové okno |
| **Chybějící kontext** | "Máš 500 errorů" | "500 errorů = 5× více než obvykle v úterý 14:00" |
| **Neprůhlednost** | Black-box ML model | Každé rozhodnutí má evidenci proč |
| **Duplicity** | 1000 stejných errorů = 1000 alertů | Normalizace + fingerprint = 1 incident |
| **Regression testing** | Není | Snapshot & replay pro porovnání |

---

## 🏗️ Architektura Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ORCHESTRACE                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ES FETCH ──▶ [A] PARSE ──▶ [B] MEASURE ──▶ [C] DETECT ──▶ [D] SCORE ──▶ [E] CLASSIFY ──▶ [F] REPORT
│                   │              │               │              │              │              │
│                   ▼              ▼               ▼              ▼              ▼              ▼
│              fingerprint     baseline        flags         score 0-100     category        JSON
│              normalized      EWMA/MAD        evidence      breakdown       subcategory     Markdown
│              grouped         trend           is_spike      severity        taxonomy        Console
│                                              is_new                                        DB
│                                              is_burst                                         
│                                                                                            
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📥 VSTUP: Fetch z Elasticsearch

### Co se stahuje

```python
# ES query
{
    "query": {
        "bool": {
            "must": [
                {"range": {"@timestamp": {"gte": "2026-01-20T10:00:00Z", "lte": "2026-01-20T10:15:00Z"}}},
                {"term": {"level": "ERROR"}}
            ]
        }
    },
    "sort": [{"@timestamp": "asc"}],
    "_source": ["message", "application.name", "@timestamp", "traceId", 
                "kubernetes.labels.eamApplication", "kubernetes.namespace", "topic"]
}
```

### Struktura raw error záznamu

```json
{
    "message": "Connection to 192.168.1.100:5432 refused for user payment_app",
    "application": "payment-service",
    "namespace": "pcb-sit-01-app",
    "timestamp": "2026-01-20T10:05:23.456Z",
    "trace_id": "abc123def456",
    "cluster": "cluster-app_pcb-sit"
}
```

### Pagination

Používá `search_after` pro neomezený fetch (ne `from/size` s limitem 10K):

```python
# První request
response = es.search(query, sort=[{"@timestamp": "asc"}], size=5000)

# Další requesty
while hits:
    last_sort = hits[-1]["sort"]
    response = es.search(query, search_after=last_sort, size=5000)
```

---

## 🔤 FÁZE A: Parse & Normalize

### Účel
Převést raw error messages na normalizovanou formu a vygenerovat fingerprint pro seskupení stejných chyb.

### Vstup → Výstup

```
VSTUP (raw):
"Connection to 192.168.1.100:5432 refused for user 1234567890"
"Connection to 192.168.1.101:5432 refused for user 9876543210"
"Connection to 10.0.0.50:5432 refused for user payment_app"

VÝSTUP (normalized):
"Connection to <IP>:<PORT> refused for user <ID>"
fingerprint: "conn_refused_5432_a1b2c3"
```

### Normalizační pravidla

| Pattern | Nahrazení | Příklad |
|---------|-----------|---------|
| IP adresy | `<IP>` | `192.168.1.100` → `<IP>` |
| Porty | `<PORT>` | `:5432` → `:<PORT>` |
| UUID | `<UUID>` | `550e8400-e29b-41d4-a716-446655440000` → `<UUID>` |
| Čísla (6+ cifer) | `<ID>` | `1234567890` → `<ID>` |
| Timestamps | `<TIMESTAMP>` | `2026-01-20T10:05:23` → `<TIMESTAMP>` |
| Emaily | `<EMAIL>` | `user@example.com` → `<EMAIL>` |
| Paths | `<PATH>` | `/var/log/app.log` → `<PATH>` |
| Hex strings | `<HEX>` | `0x7fff5fbff8c0` → `<HEX>` |

### Implementace normalizace

```python
PATTERNS = [
    # IP addresses (IPv4)
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>'),
    
    # UUIDs
    (r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<UUID>'),
    
    # Timestamps ISO
    (r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?', '<TIMESTAMP>'),
    
    # Long numbers (IDs)
    (r'\b\d{6,}\b', '<ID>'),
    
    # Emails
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '<EMAIL>'),
    
    # Hex addresses
    (r'0x[0-9a-fA-F]+', '<HEX>'),
    
    # File paths
    (r'(?:/[a-zA-Z0-9._-]+)+/?', '<PATH>'),
]

def normalize(message: str) -> str:
    result = message
    for pattern, replacement in PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result.strip()
```

### Fingerprint generování

```python
def generate_fingerprint(normalized_message: str, error_type: str, namespace: str) -> str:
    """
    Generuje unikátní hash pro seskupení stejných chyb.
    
    Komponenty:
    - normalized_message (hlavní)
    - error_type (volitelné)
    - namespace NENÍ součástí - chceme cross-namespace korelaci
    """
    content = f"{normalized_message}|{error_type or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

### Error Type extrakce

```python
def extract_error_type(message: str) -> str:
    """
    Extrahuje typ chyby z message.
    """
    # Java/Python exception pattern
    match = re.search(r'(\w+(?:Exception|Error|Failure))', message)
    if match:
        return match.group(1)
    
    # HTTP status codes
    match = re.search(r'\b(4\d{2}|5\d{2})\b', message)
    if match:
        return f"HTTP_{match.group(1)}"
    
    # Timeout patterns
    if 'timeout' in message.lower():
        return 'TimeoutError'
    
    # Connection patterns
    if 'connection' in message.lower() and ('refused' in message.lower() or 'failed' in message.lower()):
        return 'ConnectionError'
    
    return 'UnknownError'
```

### Grouping by Fingerprint

```python
def group_by_fingerprint(records: List[NormalizedRecord]) -> Dict[str, List[NormalizedRecord]]:
    """
    Seskupí záznamy podle fingerprint.
    
    Vstup: 10,000 raw errors
    Výstup: 150 skupin (fingerprints)
    """
    groups = defaultdict(list)
    for record in records:
        groups[record.fingerprint].append(record)
    return groups
```

### Výstup Fáze A

```python
@dataclass
class NormalizedRecord:
    fingerprint: str                    # "a1b2c3d4e5f6"
    normalized_message: str             # "Connection to <IP>:<PORT> refused"
    error_type: str                     # "ConnectionError"
    raw_message: str                    # Původní message (pro debug)
    timestamp: datetime                 # Čas výskytu
    namespace: str                      # "pcb-sit-01-app"
    application: str                    # "payment-service"
    trace_id: Optional[str]             # Pro linking
```

---

## 📊 FÁZE B: Measure (EWMA + MAD)

### Účel
Vypočítat baseline statistiky a aktuální metriky pro každý fingerprint.

### Proč EWMA místo průměru?

**Průměr (Simple Moving Average):**
```
Data: [10, 10, 10, 10, 100, 10, 10, 10]
Průměr: 21.25
Problém: Jeden spike před týdnem stále ovlivňuje baseline
```

**EWMA (Exponential Weighted Moving Average):**
```
Data: [10, 10, 10, 10, 100, 10, 10, 10]
EWMA (α=0.3): 12.8
Výhoda: Novější data mají větší váhu, starý spike rychle "vyprchá"
```

### EWMA výpočet

```python
def calculate_ewma(values: List[float], alpha: float = 0.3) -> float:
    """
    Exponential Weighted Moving Average
    
    α (alpha) = váha nových hodnot
    - α = 0.3 → 30% nová hodnota, 70% historie
    - α = 0.1 → pomalá reakce na změny
    - α = 0.5 → rychlá reakce na změny
    
    Vzorec: EWMA_t = α * value_t + (1-α) * EWMA_{t-1}
    """
    if not values:
        return 0.0
    
    ewma = values[0]
    for value in values[1:]:
        ewma = alpha * value + (1 - alpha) * ewma
    
    return ewma
```

### Proč MAD místo Standard Deviation?

**Standard Deviation:**
```
Data: [10, 10, 10, 10, 1000, 10, 10, 10]
StdDev: 330.7
Problém: Jeden outlier zkreslí variabilitu na měsíce
```

**MAD (Median Absolute Deviation):**
```
Data: [10, 10, 10, 10, 1000, 10, 10, 10]
Median: 10
MAD: 0 (median of |x - median|)
Výhoda: Robustní vůči outlierům
```

### MAD výpočet

```python
def calculate_mad(values: List[float]) -> float:
    """
    Median Absolute Deviation
    
    MAD = median(|x_i - median(x)|)
    
    Robustní alternativa ke stddev.
    """
    if len(values) < 2:
        return 0.0
    
    median = sorted(values)[len(values) // 2]
    deviations = [abs(x - median) for x in values]
    mad = sorted(deviations)[len(deviations) // 2]
    
    return mad
```

### Trend výpočet

```python
def calculate_trend(
    current: float, 
    baseline_ewma: float,
    baseline_mad: float
) -> Tuple[str, float]:
    """
    Vypočítá trend direction a ratio.
    
    Returns:
        direction: "increasing" | "decreasing" | "stable"
        ratio: current / baseline (e.g., 4.5 = 4.5× více než baseline)
    """
    if baseline_ewma == 0:
        return ("increasing" if current > 0 else "stable", float('inf') if current > 0 else 1.0)
    
    ratio = current / baseline_ewma
    
    # Threshold for significant change (using MAD)
    threshold = 1.0 + (baseline_mad / baseline_ewma if baseline_ewma > 0 else 0.5)
    
    if ratio > threshold:
        direction = "increasing"
    elif ratio < (1 / threshold):
        direction = "decreasing"
    else:
        direction = "stable"
    
    return (direction, ratio)
```

### Baseline zdroje

```python
def get_baseline_data(fingerprint: str, current_time: datetime) -> List[float]:
    """
    Získá historická data pro výpočet baseline.
    
    Zdroje (v pořadí priority):
    1. DB: peak_raw_data - posledních 20 oken (5 hodin)
    2. In-memory cache - pro real-time běh
    3. Default fallback - pokud není historie
    """
    # Query DB for same day_of_week, hour_of_day, quarter_hour
    # Posledních N týdnů pro stejné časové okno
    ...
```

### Výstup Fáze B

```python
@dataclass
class MeasurementResult:
    fingerprint: str
    
    # Baseline (z historie)
    baseline_ewma: float          # 10.5 errors/15min
    baseline_mad: float           # 2.3
    baseline_samples: int         # 20 (počet oken v historii)
    
    # Current (aktuální okno)
    current_count: int            # 52
    current_rate: float           # 52.0 errors/15min
    
    # Trend
    trend_direction: str          # "increasing"
    trend_ratio: float            # 4.95 (current/baseline)
    
    # Cross-namespace
    namespace_count: int          # 3 (ve 3 namespaces)
    namespaces: List[str]         # ["pcb-sit-01-app", "pcb-dev-01-app", ...]
```

---

## 🚨 FÁZE C: Detect (Boolean Flags + Evidence)

### Účel
Nastavit booleovské flagy podle jasně definovaných pravidel. Ke každému flagu přiložit důkaz (evidence).

### Detekční pravidla

#### 1. Spike Detection (is_spike)

```python
def detect_spike(measurement: MeasurementResult, threshold: float = 3.0) -> Tuple[bool, Evidence]:
    """
    SPIKE = current significantly exceeds baseline
    
    Pravidlo: current > baseline_ewma × threshold
    
    Příklad:
        baseline_ewma = 10.5
        current = 52
        threshold = 3.0
        
        52 > 10.5 × 3.0 = 31.5 → TRUE (je spike)
    """
    expected = measurement.baseline_ewma * threshold
    is_spike = measurement.current_count > expected
    
    evidence = Evidence(
        rule="spike_ewma",
        baseline=measurement.baseline_ewma,
        current=measurement.current_count,
        threshold=threshold,
        expected=expected,
        result=is_spike,
        message=f"current ({measurement.current_count}) {'>' if is_spike else '<='} "
                f"ewma ({measurement.baseline_ewma:.1f}) × {threshold} = {expected:.1f}"
    )
    
    return is_spike, evidence
```

#### 2. New Error Detection (is_new)

```python
def detect_new(fingerprint: str, known_fingerprints: Set[str]) -> Tuple[bool, Evidence]:
    """
    NEW = fingerprint nikdy předtím neviděn
    
    Kontroluje against:
    - DB: error_patterns table
    - In-memory: seen fingerprints v tomto běhu
    """
    is_new = fingerprint not in known_fingerprints
    
    evidence = Evidence(
        rule="new_fingerprint",
        fingerprint=fingerprint,
        result=is_new,
        message=f"fingerprint {fingerprint[:8]}... {'NOT' if is_new else 'already'} in known patterns"
    )
    
    return is_new, evidence
```

#### 3. Burst Detection (is_burst)

```python
def detect_burst(
    timestamps: List[datetime], 
    window_sec: int = 60,
    threshold: float = 5.0
) -> Tuple[bool, Evidence]:
    """
    BURST = náhlý nárůst v krátkém časovém okně
    
    Pravidlo: 
    - Spočítej errory v rolling window (60s)
    - Pokud max_window / avg_window > threshold → BURST
    
    Příklad:
        60s window counts: [2, 3, 2, 45, 3, 2]
        max = 45, avg = 9.5
        ratio = 45 / 9.5 = 4.7
        threshold = 5.0
        4.7 < 5.0 → FALSE (není burst)
    """
    if len(timestamps) < 2:
        return False, Evidence(rule="burst", result=False, message="not enough data")
    
    # Count errors per window
    window_counts = []
    sorted_ts = sorted(timestamps)
    
    for i, ts in enumerate(sorted_ts):
        window_end = ts + timedelta(seconds=window_sec)
        count = sum(1 for t in sorted_ts[i:] if t <= window_end)
        window_counts.append(count)
    
    max_count = max(window_counts)
    avg_count = sum(window_counts) / len(window_counts)
    
    ratio = max_count / avg_count if avg_count > 0 else 0
    is_burst = ratio > threshold
    
    evidence = Evidence(
        rule="burst",
        window_sec=window_sec,
        max_in_window=max_count,
        avg_in_window=avg_count,
        ratio=ratio,
        threshold=threshold,
        result=is_burst,
        message=f"max/avg ratio {ratio:.1f} {'>' if is_burst else '<='} {threshold}"
    )
    
    return is_burst, evidence
```

#### 4. Cross-Namespace Detection (is_cross_namespace)

```python
def detect_cross_namespace(
    namespaces: List[str],
    threshold: int = 2
) -> Tuple[bool, Evidence]:
    """
    CROSS-NAMESPACE = stejná chyba ve více namespaces
    
    Pravidlo: unique_namespaces >= threshold
    
    Význam: Pokud stejná chyba je v DEV, SIT i UAT,
    pravděpodobně jde o systémový problém, ne lokální.
    """
    unique_ns = list(set(namespaces))
    is_cross = len(unique_ns) >= threshold
    
    evidence = Evidence(
        rule="cross_namespace",
        namespaces=unique_ns,
        count=len(unique_ns),
        threshold=threshold,
        result=is_cross,
        message=f"present in {len(unique_ns)} namespaces: {', '.join(unique_ns[:5])}"
    )
    
    return is_cross, evidence
```

#### 5. Regression Detection (is_regression)

```python
def detect_regression(
    fingerprint: str,
    current_version: str,
    pattern_history: Dict
) -> Tuple[bool, Evidence]:
    """
    REGRESSION = chyba která byla opravena se vrátila
    
    Pravidlo:
    1. Fingerprint existoval v minulosti
    2. Pak zmizel (byl opraven)
    3. Teď se znovu objevil
    
    Detekce:
    - Poslední výskyt > 7 dní zpět
    - Mezitím alespoň 3 dny bez výskytu
    """
    if fingerprint not in pattern_history:
        return False, Evidence(rule="regression", result=False, message="no history")
    
    history = pattern_history[fingerprint]
    last_seen = history.get('last_seen')
    gap_days = history.get('gap_days', 0)
    
    is_regression = gap_days >= 3 and last_seen is not None
    
    evidence = Evidence(
        rule="regression",
        last_seen=last_seen,
        gap_days=gap_days,
        current_version=current_version,
        result=is_regression,
        message=f"reappeared after {gap_days} days gap" if is_regression else "continuous occurrence"
    )
    
    return is_regression, evidence
```

#### 6. Cascade Detection (is_cascade)

```python
def detect_cascade(
    fingerprint: str,
    all_detections: Dict[str, DetectionResult],
    time_window_sec: int = 300
) -> Tuple[bool, Evidence]:
    """
    CASCADE = více různých chyb ve stejném časovém okně
    
    Pravidlo: 
    - V posledních 5 minutách
    - Alespoň 3 různé fingerprints
    - Všechny mají is_spike = True
    
    Význam: Jedna root cause způsobila kaskádu chyb
    """
    recent_spikes = [
        fp for fp, det in all_detections.items()
        if det.flags.is_spike and det.time_window_overlap(fingerprint, time_window_sec)
    ]
    
    is_cascade = len(recent_spikes) >= 3
    
    evidence = Evidence(
        rule="cascade",
        related_fingerprints=recent_spikes[:10],
        count=len(recent_spikes),
        threshold=3,
        result=is_cascade,
        message=f"{len(recent_spikes)} related spikes in {time_window_sec}s window"
    )
    
    return is_cascade, evidence
```

### Výstup Fáze C

```python
@dataclass
class DetectionResult:
    fingerprint: str
    
    flags: Flags  # Všechny boolean flagy
    evidence: List[Evidence]  # Důkazy pro každý flag
    
@dataclass
class Flags:
    is_new: bool = False
    is_spike: bool = False
    is_burst: bool = False
    is_cross_namespace: bool = False
    is_regression: bool = False
    is_cascade: bool = False

@dataclass
class Evidence:
    rule: str           # "spike_ewma", "burst", ...
    result: bool        # True/False
    message: str        # Human-readable vysvětlení
    # + rule-specific fields (baseline, threshold, etc.)
```

---

## 🔢 FÁZE D: Score (Váhová funkce)

### Účel
Převést boolean flagy na numerické skóre 0-100 pomocí deterministické váhové funkce.

### Váhy (konfigurovatelné)

```python
@dataclass
class ScoreWeights:
    # Base score (z počtu errorů)
    base_multiplier: float = 10.0    # base = count / multiplier
    base_max: float = 30.0           # cap na 30 bodů
    
    # Flag bonuses
    spike_weight: float = 25.0       # +25 za spike
    burst_weight: float = 20.0       # +20 za burst
    new_weight: float = 15.0         # +15 za novou chybu
    regression_weight: float = 35.0  # +35 za regresi (nejvíc!)
    cascade_weight: float = 20.0     # +20 za kaskádu
    cross_ns_weight: float = 15.0    # +15 za cross-namespace
    
    # Scaling bonuses
    trend_ratio_weight: float = 2.0  # +2 za každý 1.0 ratio nad 2.0
    namespace_count_weight: float = 3.0  # +3 za každý namespace nad 2
    
    # Maximum
    max_score: float = 100.0
```

### Výpočet skóre

```python
def calculate_score(
    detection: DetectionResult,
    measurement: MeasurementResult,
    weights: ScoreWeights
) -> Tuple[float, ScoreBreakdown]:
    """
    Score = base + sum(flag_bonuses) + scaling_bonuses
    
    Deterministické - žádné if/else podmínky v hlavní logice.
    Používá bool * weight = weight if True, 0 if False.
    """
    breakdown = ScoreBreakdown()
    
    # Base score (z počtu errorů)
    breakdown.base = min(
        measurement.current_count / weights.base_multiplier,
        weights.base_max
    )
    
    # Flag bonuses (bool * weight)
    breakdown.spike_bonus = int(detection.flags.is_spike) * weights.spike_weight
    breakdown.burst_bonus = int(detection.flags.is_burst) * weights.burst_weight
    breakdown.new_bonus = int(detection.flags.is_new) * weights.new_weight
    breakdown.regression_bonus = int(detection.flags.is_regression) * weights.regression_weight
    breakdown.cascade_bonus = int(detection.flags.is_cascade) * weights.cascade_weight
    breakdown.cross_ns_bonus = int(detection.flags.is_cross_namespace) * weights.cross_ns_weight
    
    # Scaling bonuses
    if measurement.trend_ratio > 2.0:
        extra_ratio = min(5.0, measurement.trend_ratio - 2.0)
        breakdown.spike_bonus += extra_ratio * weights.trend_ratio_weight
    
    if measurement.namespace_count > 2:
        extra_ns = min(5, measurement.namespace_count - 2)
        breakdown.cross_ns_bonus += extra_ns * weights.namespace_count_weight
    
    # Total
    breakdown.total = min(
        breakdown.base + 
        breakdown.spike_bonus + 
        breakdown.burst_bonus +
        breakdown.new_bonus +
        breakdown.regression_bonus +
        breakdown.cascade_bonus +
        breakdown.cross_ns_bonus,
        weights.max_score
    )
    
    return breakdown.total, breakdown
```

### Příklad výpočtu

```
Incident: ConnectionError ve 3 namespaces, 52 errorů (4.95× baseline)

Flags:
  is_spike: True
  is_cross_namespace: True
  is_new: False
  is_regression: False
  is_burst: False
  is_cascade: False

Výpočet:
  base:           52 / 10 = 5.2        →  5
  spike_bonus:    True × 25 = 25       → 25
  cross_ns_bonus: True × 15 = 15       → 15
  
  Scaling:
    trend_ratio 4.95 > 2.0:
      extra = min(5, 4.95 - 2.0) = 2.95
      spike_bonus += 2.95 × 2 = +6     → 31 (total spike)
    
    namespace_count 3 > 2:
      extra = min(5, 3 - 2) = 1
      cross_ns_bonus += 1 × 3 = +3     → 18 (total cross_ns)

  TOTAL: 5 + 31 + 18 = 54

Score Breakdown:
{
    "base": 5,
    "spike_bonus": 31,
    "cross_ns_bonus": 18,
    "burst_bonus": 0,
    "new_bonus": 0,
    "regression_bonus": 0,
    "cascade_bonus": 0,
    "total": 54
}
```

### Severity mapování

```python
def score_to_severity(score: float) -> IncidentSeverity:
    """
    Score → Severity mapping
    
    80-100: CRITICAL  (okamžitá akce)
    60-79:  HIGH      (řešit brzy)
    40-59:  MEDIUM    (naplánovat)
    20-39:  LOW       (sledovat)
    0-19:   INFO      (informativní)
    """
    if score >= 80:
        return IncidentSeverity.CRITICAL
    elif score >= 60:
        return IncidentSeverity.HIGH
    elif score >= 40:
        return IncidentSeverity.MEDIUM
    elif score >= 20:
        return IncidentSeverity.LOW
    else:
        return IncidentSeverity.INFO
```

---

## 🏷️ FÁZE E: Classify (Taxonomy)

### Účel
Kategorizovat incident podle obsahu error message pro lepší routing a reporting.

### Taxonomy struktura

```
Categories:
├── memory
│   ├── out_of_memory
│   ├── memory_leak
│   └── gc_overhead
│
├── database
│   ├── connection_failed
│   ├── connection_timeout
│   ├── deadlock
│   ├── constraint_violation
│   ├── query_timeout
│   └── transaction_failed
│
├── network
│   ├── connection_refused
│   ├── connection_reset
│   ├── timeout
│   ├── dns_resolution
│   ├── ssl_handshake
│   └── socket_error
│
├── auth
│   ├── unauthorized (401)
│   ├── forbidden (403)
│   ├── token_expired
│   ├── invalid_credentials
│   └── session_expired
│
├── http
│   ├── bad_request (400)
│   ├── not_found (404)
│   ├── method_not_allowed (405)
│   ├── conflict (409)
│   ├── internal_server_error (500)
│   ├── bad_gateway (502)
│   ├── service_unavailable (503)
│   └── gateway_timeout (504)
│
├── business
│   ├── validation_error
│   ├── business_rule_violation
│   ├── data_integrity
│   └── workflow_error
│
├── external
│   ├── api_error
│   ├── third_party_failure
│   └── integration_error
│
├── infrastructure
│   ├── disk_full
│   ├── cpu_overload
│   ├── resource_exhausted
│   └── container_crash
│
└── unknown
    └── unclassified
```

### Klasifikační pravidla

```python
CLASSIFICATION_RULES = [
    # Memory
    (r'out\s*of\s*memory|oom|heap\s*space', 'memory', 'out_of_memory'),
    (r'memory\s*leak|growing\s*heap', 'memory', 'memory_leak'),
    (r'gc\s*overhead|garbage\s*collect', 'memory', 'gc_overhead'),
    
    # Database
    (r'connection.*(?:refused|failed|closed).*(?:postgres|mysql|oracle|db)', 'database', 'connection_failed'),
    (r'deadlock', 'database', 'deadlock'),
    (r'constraint\s*violation|duplicate\s*key|unique.*constraint', 'database', 'constraint_violation'),
    (r'query.*timeout|statement.*timeout', 'database', 'query_timeout'),
    
    # Network
    (r'connection\s*refused', 'network', 'connection_refused'),
    (r'connection\s*reset', 'network', 'connection_reset'),
    (r'(?:read|connect|socket)\s*timed?\s*out', 'network', 'timeout'),
    (r'dns|name\s*resolution|unknown\s*host', 'network', 'dns_resolution'),
    (r'ssl|tls|handshake|certificate', 'network', 'ssl_handshake'),
    
    # Auth
    (r'401|unauthorized', 'auth', 'unauthorized'),
    (r'403|forbidden|access\s*denied', 'auth', 'forbidden'),
    (r'token.*(?:expired|invalid)|jwt.*(?:expired|invalid)', 'auth', 'token_expired'),
    
    # HTTP status codes
    (r'\b400\b|bad\s*request', 'http', 'bad_request'),
    (r'\b404\b|not\s*found', 'http', 'not_found'),
    (r'\b500\b|internal\s*(?:server\s*)?error', 'http', 'internal_server_error'),
    (r'\b502\b|bad\s*gateway', 'http', 'bad_gateway'),
    (r'\b503\b|service\s*unavailable', 'http', 'service_unavailable'),
    (r'\b504\b|gateway\s*timeout', 'http', 'gateway_timeout'),
    
    # Business
    (r'validation.*(?:failed|error)|invalid.*(?:input|data|format)', 'business', 'validation_error'),
    
    # External
    (r'api.*(?:error|failed)|external.*(?:service|api)', 'external', 'api_error'),
]

def classify(message: str, error_type: str) -> Tuple[str, str]:
    """
    Klasifikuje error message do category/subcategory.
    
    Returns:
        (category, subcategory)
    """
    message_lower = message.lower()
    
    for pattern, category, subcategory in CLASSIFICATION_RULES:
        if re.search(pattern, message_lower):
            return (category, subcategory)
    
    # Fallback based on error_type
    if error_type:
        if 'Connection' in error_type:
            return ('network', 'connection_error')
        if 'Timeout' in error_type:
            return ('network', 'timeout')
        if 'SQL' in error_type or 'Database' in error_type:
            return ('database', 'query_error')
    
    return ('unknown', 'unclassified')
```

### Výstup Fáze E

```python
@dataclass
class ClassificationResult:
    fingerprint: str
    category: str           # "network"
    subcategory: str        # "connection_refused"
    confidence: float       # 0.95 (jak jistá je klasifikace)
    matched_rule: str       # Pattern který matchnul
```

---

## 📄 FÁZE F: Report (Render)

### Účel
Sestavit finální Incident Object a vygenerovat výstupy v různých formátech.

### Incident Object Assembly

```python
def build_incident(
    fingerprint: str,
    records: List[NormalizedRecord],
    measurement: MeasurementResult,
    detection: DetectionResult,
    score_result: ScoreResult,
    classification: ClassificationResult
) -> Incident:
    """
    Sestaví kompletní Incident Object z výstupů všech fází.
    """
    return Incident(
        id=generate_incident_id(),
        fingerprint=fingerprint,
        
        # Z FÁZE A
        normalized_message=records[0].normalized_message,
        error_type=records[0].error_type,
        raw_samples=[r.raw_message for r in records[:5]],  # Max 5 samples
        
        # Z FÁZE B
        time=TimeInfo(
            first_seen=min(r.timestamp for r in records),
            last_seen=max(r.timestamp for r in records),
            duration_sec=(max_ts - min_ts).total_seconds()
        ),
        stats=Stats(
            baseline_ewma=measurement.baseline_ewma,
            baseline_mad=measurement.baseline_mad,
            current_count=measurement.current_count,
            current_rate=measurement.current_rate,
            trend_direction=measurement.trend_direction,
            trend_ratio=measurement.trend_ratio
        ),
        apps=list(set(r.application for r in records)),
        namespaces=measurement.namespaces,
        
        # Z FÁZE C
        flags=detection.flags,
        evidence=detection.evidence,
        
        # Z FÁZE D
        score=score_result.score,
        score_breakdown=score_result.breakdown,
        severity=score_to_severity(score_result.score),
        
        # Z FÁZE E
        category=classification.category,
        subcategory=classification.subcategory
    )
```

### Output formáty

#### JSON

```python
def to_json(incidents: List[Incident]) -> str:
    return json.dumps({
        "report_time": datetime.now().isoformat(),
        "summary": {
            "total": len(incidents),
            "by_severity": count_by_severity(incidents),
            "by_category": count_by_category(incidents)
        },
        "incidents": [asdict(inc) for inc in incidents]
    }, indent=2, default=str)
```

#### Markdown

```python
def to_markdown(incidents: List[Incident]) -> str:
    md = f"# Incident Report {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    md += "## Summary\n\n"
    md += f"| Severity | Count |\n|----------|-------|\n"
    for sev, count in count_by_severity(incidents).items():
        md += f"| {sev} | {count} |\n"
    
    md += "\n## Critical & High Incidents\n\n"
    for inc in sorted(incidents, key=lambda x: x.score, reverse=True):
        if inc.severity in ['critical', 'high']:
            md += render_incident_md(inc)
    
    return md
```

#### Console

```python
def to_console(incidents: List[Incident]) -> None:
    print("=" * 70)
    print(f"📊 INCIDENT REPORT - {datetime.now()}")
    print("=" * 70)
    
    severity_emoji = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🔵', 'info': '⚪'}
    
    for sev, count in count_by_severity(incidents).items():
        print(f"  {severity_emoji[sev]} {sev.upper()}: {count}")
    
    print("\nTop Incidents:")
    for inc in sorted(incidents, key=lambda x: x.score, reverse=True)[:10]:
        emoji = severity_emoji[inc.severity]
        print(f"  [{inc.score:2.0f}] {emoji} {inc.category}/{inc.subcategory} - "
              f"{len(inc.namespaces)} ns, {inc.stats.current_count} errors "
              f"({inc.stats.trend_ratio:.1f}× baseline)")
```

---

## 🔄 ORCHESTRACE: Pipeline V4

### Hlavní flow

```python
class PipelineV4:
    def run(self, raw_errors: List[Dict], run_id: str = None) -> IncidentCollection:
        """
        Orchestrace všech fází.
        """
        print(f"[A] PARSE: {len(raw_errors)} raw errors")
        records = self.phase_a.parse_batch(raw_errors)
        grouped = group_by_fingerprint(records)
        print(f"    → {len(grouped)} unique fingerprints")
        
        print(f"[B] MEASURE: calculating baselines")
        measurements = self.phase_b.measure_batch(grouped)
        print(f"    → {len(measurements)} measurements")
        
        print(f"[C] DETECT: applying detection rules")
        detections = self.phase_c.detect_batch(grouped, measurements)
        print(f"    → {sum(1 for d in detections.values() if any_flag(d))} with flags")
        
        print(f"[D] SCORE: calculating scores")
        scores = self.phase_d.score_batch(detections, measurements)
        print(f"    → scores range: {min_score} - {max_score}")
        
        print(f"[E] CLASSIFY: categorizing")
        classifications = self.phase_e.classify_batch(grouped)
        print(f"    → {len(set(c.category for c in classifications.values()))} categories")
        
        print(f"[F] REPORT: building incidents")
        incidents = self.phase_f.build_incidents(
            grouped, measurements, detections, scores, classifications
        )
        
        return IncidentCollection(incidents=incidents)
```

### Příklad průběhu

```
================================================================================
🚀 PIPELINE V4 - Run ID: regular-20260120-1000
================================================================================

[A] PARSE: 12,847 raw errors
    → 234 unique fingerprints

[B] MEASURE: calculating baselines
    → 234 measurements
    → baseline sources: 189 from DB, 45 from defaults

[C] DETECT: applying detection rules
    → 47 with flags
       - spike: 23
       - new: 8
       - burst: 3
       - cross_namespace: 12
       - regression: 1

[D] SCORE: calculating scores
    → scores range: 5 - 87
    → severity distribution: 2 critical, 8 high, 15 medium, 22 low

[E] CLASSIFY: categorizing
    → 6 categories
       - network: 18
       - database: 12
       - auth: 8
       - http: 5
       - business: 3
       - unknown: 1

[F] REPORT: building incidents
    → 47 incidents built

================================================================================
✅ PIPELINE COMPLETE - 3.2s
================================================================================
```

---

## 📊 Kompletní Incident Object (výstup)

```json
{
  "id": "inc-20260120-1000-001",
  "fingerprint": "a1b2c3d4e5f6",
  
  "normalized_message": "Connection to <IP>:<PORT> refused for user <ID>",
  "error_type": "ConnectionError",
  "raw_samples": [
    "Connection to 192.168.1.100:5432 refused for user payment_app",
    "Connection to 192.168.1.101:5432 refused for user order_app"
  ],
  
  "time": {
    "first_seen": "2026-01-20T10:00:12.456Z",
    "last_seen": "2026-01-20T10:14:58.123Z",
    "duration_sec": 886
  },
  
  "stats": {
    "baseline_ewma": 10.5,
    "baseline_mad": 2.3,
    "baseline_samples": 20,
    "current_count": 52,
    "current_rate": 52.0,
    "trend_direction": "increasing",
    "trend_ratio": 4.95
  },
  
  "apps": ["payment-service", "order-service"],
  "namespaces": ["pcb-sit-01-app", "pcb-dev-01-app", "pcb-uat-01-app"],
  "versions": ["2.3.1", "2.3.0"],
  
  "flags": {
    "is_new": false,
    "is_spike": true,
    "is_burst": false,
    "is_cross_namespace": true,
    "is_regression": false,
    "is_cascade": false
  },
  
  "evidence": [
    {
      "rule": "spike_ewma",
      "baseline": 10.5,
      "current": 52,
      "threshold": 3.0,
      "expected": 31.5,
      "result": true,
      "message": "current (52) > ewma (10.5) × 3.0 = 31.5"
    },
    {
      "rule": "cross_namespace",
      "namespaces": ["pcb-sit-01-app", "pcb-dev-01-app", "pcb-uat-01-app"],
      "count": 3,
      "threshold": 2,
      "result": true,
      "message": "present in 3 namespaces: pcb-sit-01-app, pcb-dev-01-app, pcb-uat-01-app"
    },
    {
      "rule": "burst",
      "window_sec": 60,
      "max_in_window": 12,
      "avg_in_window": 8.5,
      "ratio": 1.41,
      "threshold": 5.0,
      "result": false,
      "message": "max/avg ratio 1.41 <= 5.0"
    }
  ],
  
  "score": 72,
  "score_breakdown": {
    "base": 5,
    "spike_bonus": 31,
    "burst_bonus": 0,
    "new_bonus": 0,
    "regression_bonus": 0,
    "cascade_bonus": 0,
    "cross_ns_bonus": 18,
    "total": 72
  },
  
  "severity": "high",
  "category": "network",
  "subcategory": "connection_refused"
}
```

---

## 🚀 Quick Start

```bash
# 1. Setup
unzip ai-log-analyzer-v4-complete.zip && cd ai-log-analyzer-complete
cp config/.env.example .env && vim .env
pip install -r requirements.txt

# 2. DB migrace
psql -f scripts/migrations/000_create_base_tables.sql
psql -f scripts/migrations/001_create_peak_thresholds.sql

# 3. INIT (21 dní baseline)
./run_init.sh --days 21

# 4. Thresholds
python scripts/core/calculate_peak_thresholds.py

# 5. Backfill (14 dní s detekcí)
./run_backfill.sh --days 14 --workers 4

# 6. Cron
*/15 * * * * /path/to/run_regular.sh --quiet
```

---

## 📈 Performance

| Operace | Čas | Poznámka |
|---------|-----|----------|
| ES fetch 50K errors | ~30s | search_after pagination |
| Pipeline 50K → incidents | ~60s | all 6 phases |
| DB batch insert 10K | ~2s | execute_values |
| Backfill 1 den | ~2-3 min | --workers 4 |
| Regular 15-min window | ~30s | typicky 1-5K errors |

---

**Verze:** 4.0 | **Maintainer:** AI Log Analyzer Team
