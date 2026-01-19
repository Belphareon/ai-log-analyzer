# 🔧 DB SCHEMA & NAMING CONVENTION - Implementation Plan

**Datum:** 2026-01-09  
**Status:** Planning Phase  
**Účel:** Vytvořit jednotnou DB strukturu pro Phase 5B-6 s jasným naming convention

---

## 📊 CURRENT STATE

### ❌ Problém
- DB tabulky neexistují (jen `pg_stat_statements`)
- .env soubor má špatné credentials (localhost místo P050TD01)
- Nemáme definovaný naming convention pro tabulky, sloupce

### ✅ Co máme
- DB: `ailog_analyzer` na `P050TD01.DEV.KB.CZ:5432`
- Schema: `ailog_peak` (mělo by existovat)
- User: `ailog_analyzer_user_d1` (data operations)
- DDL User: `ailog_analyzer_ddl_user_d1` (schema operations)

---

## 🎯 PLAN - Co se bude dělat

### FÁZE 1: DB SETUP & SCHEMA CREATION

#### 1.1 Vytvořit .env s správnými credentials
- **Soubor:** `.env`
- **Změny:**
  ```
  DB_HOST=P050TD01.DEV.KB.CZ
  DB_PORT=5432
  DB_NAME=ailog_analyzer
  DB_USER=ailog_analyzer_user_d1
  DB_PASSWORD=<DOPLNIT - z SMAX/emailu>
  DB_DDL_USER=ailog_analyzer_ddl_user_d1
  DB_DDL_PASSWORD=<DOPLNIT - z SMAX/emailu>
  ```
- **Stav:** ⏳ PENDING - čekám na hesla

#### 1.2 Vytvořit/Ověřit schema `ailog_peak`
- **Script:** `scripts/setup_peak_db.py` (upravit/vytvořit)
- **Operace:**
  ```sql
  CREATE SCHEMA IF NOT EXISTS ailog_peak;
  ```
- **Stav:** ⏳ TODO

---

### FÁZE 2: TABULKY & NAMING CONVENTION

#### 2.1 Tabulka: `ailog_peak.peak_statistics`

**Primární tabulka pro ingestion**

```sql
CREATE TABLE ailog_peak.peak_statistics (
  -- Primární identifikátory
  id SERIAL PRIMARY KEY,
  
  -- Časové informace
  day_of_week INT NOT NULL,           -- 0-6 (Mon-Sun)
  hour_of_day INT NOT NULL,           -- 0-23
  quarter_hour INT NOT NULL,          -- 0-3 (00, 15, 30, 45 minut)
  
  -- Metadata
  namespace VARCHAR(255) NOT NULL,    -- Např: pcb-dev-01-app
  
  -- Statistiky
  value FLOAT NOT NULL,               -- Počet errorů v okně
  
  -- Tracking
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  
  -- Indexy
  UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
);

CREATE INDEX idx_ps_namespace ON ailog_peak.peak_statistics(namespace);
CREATE INDEX idx_ps_time_window ON ailog_peak.peak_statistics(day_of_week, hour_of_day, quarter_hour);
```

**Logika:**
- Uklád Ás normální hodnoty (bez peaks)
- Peaks se nahrazují referenční hodnotou (replacement_value)
- Chybějící okna se vyplní mean=0
- Normalizace během reference calc: 0 → 1

---

#### 2.2 Tabulka: `ailog_peak.peak_investigation`

**Detailní analýza detekovaných peaks**

```sql
CREATE TABLE ailog_peak.peak_investigation (
  -- Primární identifikátory
  id SERIAL PRIMARY KEY,
  
  -- Časové informace (kdy se peak stal?)
  day_of_week INT NOT NULL,
  hour_of_day INT NOT NULL,
  quarter_hour INT NOT NULL,
  
  -- Metadata
  namespace VARCHAR(255) NOT NULL,    -- Kterou app/NS se to týká?
  app_version VARCHAR(100),           -- Verze aplikace v daný čas
  
  -- Peak data
  original_value FLOAT NOT NULL,      -- Originální hodnota (peak)
  reference_value FLOAT NOT NULL,     -- Referenční baseline
  replacement_value FLOAT,            -- Čím se nahradil (pokud null, skip)
  ratio FLOAT NOT NULL,               -- original_value / reference_value
  
  -- Investigace context
  context_before JSONB,               -- ±15min okna PŘED (co se dělo)
  context_after JSONB,                -- ±15min okna PO (co se dělo)
  
  -- Status & Tags
  peak_type VARCHAR(50),              -- 'recurring', 'anomaly', 'known'
  known_cause VARCHAR(255),           -- Pokud je to známý peak
  ai_analysis TEXT,                   -- Output z LLM analýzy
  
  -- Tracking
  created_at TIMESTAMP DEFAULT NOW(),
  resolved_at TIMESTAMP,              -- Kdy se peak vyřešil (pokud vůbec)
  
  -- Indexy
  UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
);

CREATE INDEX idx_pi_namespace ON ailog_peak.peak_investigation(namespace);
CREATE INDEX idx_pi_peak_type ON ailog_peak.peak_investigation(peak_type);
CREATE INDEX idx_pi_created_at ON ailog_peak.peak_investigation(created_at DESC);
```

**Logika:**
- Zaznamenává VŠECHNY detekované peaks
- Ukládá context (co se dělo před/po)
- Linked na LLM pro AI analýzu
- Tracking: je-li peak recurring, anomaly, nebo já znám příčinu?

---

#### 2.3 Tabulka: `ailog_peak.peak_patterns`

**Tracking rekurentních peaks (pro self-learning)**

```sql
CREATE TABLE ailog_peak.peak_patterns (
  -- Primární identifikátory
  id SERIAL PRIMARY KEY,
  pattern_hash VARCHAR(64),           -- MD5(namespace + day_of_week + hour + quarter) 
  
  -- Pattern metadata
  namespace VARCHAR(255) NOT NULL,
  day_of_week INT,                    -- NULL = všechny dny
  hour_of_day INT,                    -- NULL = všechny hodiny
  quarter_hour INT,                   -- NULL = všechny čtvrthodinky
  
  -- Statistics
  occurrence_count INT DEFAULT 1,     -- Kolikrát jsme viděli tento peak?
  avg_original_value FLOAT,           -- Průměrná height peaku
  last_seen TIMESTAMP,
  first_seen TIMESTAMP,
  
  -- AI & Knowledge
  probable_cause VARCHAR(500),        -- Co to asi způsobuje?
  confidence FLOAT DEFAULT 0.5,       -- 0.0-1.0 (confidence v příčině)
  recommended_action VARCHAR(500),    -- Co dělat?
  
  -- Status
  is_known BOOLEAN DEFAULT FALSE,     -- Jestli víme co to je
  is_resolved BOOLEAN DEFAULT FALSE,  -- Jestli jsme to vyřešili
  resolution_notes TEXT,
  
  -- Tracking
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  
  UNIQUE (pattern_hash)
);

CREATE INDEX idx_pp_namespace ON ailog_peak.peak_patterns(namespace);
CREATE INDEX idx_pp_is_known ON ailog_peak.peak_patterns(is_known);
CREATE INDEX idx_pp_last_seen ON ailog_peak.peak_patterns(last_seen DESC);
```

**Logika:**
- Agreguje rekurentní peaks v stejný čas/namespace
- Učí se: jestli je to nový peak nebo opakující se?
- Tracking: je-li vyřešen? Jaká byla příčina?

---

### FÁZE 3: INGESTION SCRIPTS (Co se změní)

#### 3.1 Script: `scripts/ingest_from_log.py`

**NOVÉ FUNKCIONALITY:**

```python
def ingest_peak_statistics_with_detection(log_file, statistics):
    """
    1. Parsuj data z logu
    2. Detekuj peaky (4+4 rule)
    3. Nahraď peaky referenční hodnotou
    4. Insert do peak_statistics
    5. Zaznamenej peaky do peak_investigation
    6. Vyplň chybějící okna (mean=0)
    """
    
    # STEP 1: Parse & Load data
    statistics = parse_peak_statistics_from_log(log_file)
    
    # STEP 2: Iterate all values
    for (day, hour, quarter, namespace), stats in statistics.items():
        value = stats['mean']
        
        # STEP 3: Detect peak
        is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
            day, hour, quarter, namespace, value, statistics
        )
        
        if is_peak:
            # 3a: Record to peak_investigation
            insert_peak_investigation(
                day, hour, quarter, namespace,
                original_value=value,
                reference_value=reference,
                ratio=ratio
            )
            
            # 3b: Replace value
            replacement_value = reference
        else:
            replacement_value = value
        
        # STEP 4: Insert to DB (ALWAYS - no gaps!)
        insert_to_peak_statistics(
            day, hour, quarter, namespace,
            value=replacement_value
        )
    
    # STEP 5: Fill missing windows
    fill_missing_windows()
    
    # STEP 6: Verify
    verify_distribution()
```

**Změny v kódu:**
- Nová funcke: `insert_peak_investigation()`
- Integrovaný `fill_missing_windows()` - bez separátního scriptu
- Logování všech peaks

**Stav:** ⏳ TODO - napsat/upravit

---

#### 3.2 Script: `scripts/analyze_peaks_with_llm.py`

**NOVÝ - AI analýza peaks**

```python
def analyze_peaks_with_llm():
    """
    1. Přečti všechny peaks z peak_investigation
    2. Seskupuj po pattern (recurring vs. anomaly)
    3. Pro každý pattern: zavolej LLM
    4. Ulož výsledky do peak_investigation.ai_analysis
    5. Aktualizuj peak_patterns tabulku
    """
    
    # Load unanalyzed peaks
    peaks = load_unanalyzed_peaks()
    
    for peak in peaks:
        # Get context from surrounding windows
        context = get_peak_context(peak)
        
        # Call LLM
        analysis = call_ollama_api({
            'namespace': peak.namespace,
            'time': f"{peak.day_of_week} {peak.hour_of_day}:{peak.quarter_hour*15:02d}",
            'peak_value': peak.original_value,
            'reference': peak.reference_value,
            'ratio': peak.ratio,
            'context_before': context['before'],
            'context_after': context['after']
        })
        
        # Save analysis
        update_peak_investigation(peak.id, ai_analysis=analysis)
        
        # Update/create pattern
        update_peak_pattern(peak, analysis)
```

**Stav:** ⏳ TODO - vytvořit

---

### FÁZE 4: VERIFICATION & VALIDATION

#### 4.1 Script: `scripts/verify_db_integrity.py`

**Kontroluje:**
- Všechny NS mají všechna okna (7×96×12 = 8,064 řádků)
- Žádné NULL hodnoty
- Value range: 0-1000 (peaks by měly být nahrazeny)
- peak_investigation records jsou in-sync s replacementem

**Stav:** ⏳ TODO - vytvořit

---

## 📋 NAMING CONVENTION (Jednotný styl)

### Tabulky
- `ailog_peak.peak_statistics` - Normální data
- `ailog_peak.peak_investigation` - Detaily peaks
- `ailog_peak.peak_patterns` - Agregované patterns

### Sloupce (Generální pravidla)
- `*_at` - Timestamps (created_at, updated_at, resolved_at)
- `*_value` - Numerické hodnoty (original_value, reference_value)
- `*_count` - Počty (occurrence_count)
- `is_*` - Boolean flags (is_known, is_resolved)
- `*_type` - Kategorie (peak_type)
- Camel-case: `dayOfWeek` → ❌, `day_of_week` → ✅

### Scripts
- `ingest_*` - Data ingestion
- `verify_*` - Validace & kontrola
- `analyze_*` - Analýza dat
- `export_*` - Export/extraction

---

## ✅ IMPLEMENTAČNÍ CHECKLIST

- [ ] **1.1** Doplnit .env credentials
- [ ] **1.2** Spustit `scripts/setup_peak_db.py` (create schema)
- [ ] **2.1** Create table: `peak_statistics`
- [ ] **2.2** Create table: `peak_investigation`
- [ ] **2.3** Create table: `peak_patterns`
- [ ] **3.1** Upravit `ingest_from_log.py` - Peak Detection + Investigation
- [ ] **3.2** Nový script: `analyze_peaks_with_llm.py`
- [ ] **4.1** Nový script: `verify_db_integrity.py`
- [ ] **5.0** Spustit INIT Phase 1 (1.12-7.12) ingestion
- [ ] **6.0** Spustit INIT Phase 2 (8.12-14.12) ingestion
- [ ] **7.0** Spustit REGULAR Phase (15.12+)
- [ ] **8.0** Update `working_progress.md` + commit

---

## 📝 NEXT ACTIONS (Pořadí spouštění)

### DNES (2026-01-09)
1. Doplnit .env s DB credentials
2. Vytvořit schema + tabulky
3. Napsat detail plan pro ingest_from_log.py změny

### ZÍTŘA (2026-01-10)
1. Upravit ingest_from_log.py
2. Testovat na Phase 1 data (1.12-7.12)
3. Verifikovat data v DB

### POZDĚJI
1. Analyzovat peaks s LLM
2. Implementovat self-learning
3. Deploy to K8s

---

**Stav:** 🔄 IN PLANNING  
**Maintainer:** jvsete  
**Last Updated:** 2026-01-09 10:30 UTC
