# Přidání application.version do Incident Analysis

## Problém

Bez verze aplikace nemůžeš:
- Detekovat regrese po deployi
- Správně doporučit rollback
- Vytvořit hypotézu "incident začal po deploy v1.8.4"

## Řešení

### 1. ES → DB: Přidat sloupec `application_version`

```sql
-- Migrace
ALTER TABLE ailog_peak.peak_investigation 
ADD COLUMN application_version VARCHAR(50);

-- Index pro rychlé filtrování
CREATE INDEX idx_peak_inv_app_version 
ON ailog_peak.peak_investigation(namespace, application_version);
```

### 2. Fetch z ES: Přidat pole `application.version`

V `fetch_unlimited.py` nebo pipeline:

```python
# ES query - přidat do _source
"_source": [
    "timestamp",
    "namespace", 
    "message",
    "application.version",  # ← PŘIDAT
    # ...
]

# Při zpracování
version = hit.get('_source', {}).get('application', {}).get('version', '')
```

### 3. Insert do DB: Uložit verzi

V `regular_phase.py` / `backfill.py`:

```python
data.append((
    ts,
    ts.weekday(),
    # ...
    incident.version,  # ← PŘIDAT do INSERT
))
```

### 4. Load pro analýzu: Načíst verzi

V `analyze_incidents.py`, upravit SQL:

```python
cursor.execute("""
    SELECT 
        timestamp, namespace, original_value, reference_value,
        is_new, is_spike, is_burst, is_cross_namespace,
        error_type, error_message, score, severity,
        application_version  -- ← PŘIDAT
    FROM ailog_peak.peak_investigation
    WHERE timestamp >= %s AND timestamp < %s
    ORDER BY timestamp
""", (date_from, date_to))
```

A při vytváření incidentu:

```python
version = row[12]  # application_version
if version:
    app = ns.split('-')[0]  # nebo jiná logika
    inc.scope.app_versions[app] = [version]
```

### 5. Výsledek

Incident Analysis automaticky:
- Detekuje `version_change_detected`
- Zobrazí v FACTS: `⚠️ VERSION CHANGE: order-service (1.8.3 → 1.8.4)`
- Upraví IMMEDIATE ACTIONS: `Review recent deployment of order-service (1.8.3, 1.8.4)`
- Posílí hypothesis (pokud verze koreluje s incident start)

## Quick Test

Pokud nemáš verzi v ES, můžeš ji dočasně extrahovat z namespace:

```python
# Např. order-service-v1.8.4-prod → v1.8.4
import re
match = re.search(r'v\d+\.\d+\.\d+', namespace)
version = match.group() if match else None
```

Ale to je workaround - správné řešení je mít `application.version` v ES.
