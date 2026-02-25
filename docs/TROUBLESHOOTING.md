# Troubleshooting - AI Log Analyzer

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
