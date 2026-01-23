# Quick Start - AI Log Analyzer v5.3.1

## 5 minut k prvnímu reportu

### 1. Instalace (1 min)

```bash
pip install psycopg2-binary python-dotenv requests pyyaml
```

### 2. Konfigurace (2 min)

```bash
cp config/.env.example config/.env
# Upravit DB_* a ES_* proměnné
```

### 3. Spuštění (1 min)

```bash
python scripts/regular_phase_v5.3.py
```

### 4. Výsledky (1 min)

```bash
# Report
cat scripts/reports/incident_analysis_15min_*.txt

# Registry
cat registry/known_errors.yaml
```

## Co se stane

```
1. Fetch logů z ES (posledních 15 min)
2. Detekce anomálií (EWMA/MAD)
3. Analýza incidentů (role, propagace)
4. Knowledge matching (KNOWN vs NEW)
5. Registry update (append-only)
6. Report generace (VŽDY, i prázdný)
```

## Výstup

### Report (scripts/reports/)

```
======================================================================
🔍 INCIDENT ANALYSIS - 15 MIN OPERATIONAL REPORT
======================================================================
Period: 09:00 - 09:15

⚠️ 2 INCIDENT(S) DETECTED
   🆕 1 NEW | 📚 1 KNOWN

────────────────────────────────────────────────────────────
🔴 [P1] 🆕 NEW INCIDENT (09:01–09:06)
────────────────────────────────────────────────────────────

FACTS:
  • order-service: HikariPool-1 - Connection is not available
  • Root: order-service
  • Downstream: payment-service
  • ⚡ PROPAGATED in 25s across 2 apps

IMMEDIATE ACTIONS:
  1. URGENT: Fast propagation detected (25s)
  2. Check DB connection pool on order-service
```

### Registry (registry/)

```yaml
# known_errors.yaml - automaticky aktualizováno
- id: KE-000001
  fingerprint: 9fa2c41e8c3a1b2d
  first_seen: "2026-01-23T09:12:41"
  last_seen: "2026-01-23T09:12:41"
  occurrences: 1
  affected_apps: [order-service]
  status: OPEN
```

## Další kroky

### Cron (automatizace)

```bash
*/15 * * * * cd /path/to && python scripts/regular_phase_v5.3.py --quiet
```

### Backfill (historie)

```bash
python scripts/backfill_v5.3.py --days 7
```

### Knowledge Base (známé errory)

```yaml
# config/known_issues/known_errors.yaml
- id: KE-001
  fingerprint: database|connection_pool|hikari
  description: Known DB pool issue
  jira: OPS-431
```

## Troubleshooting

### Prázdný report?

v5.3.1 generuje report VŽDY. Pokud je prázdný:
- Zkontrolujte `scripts/reports/` - soubor by měl existovat
- Prázdný report = žádné incidenty = OK

### Registry se neaktualizuje?

```bash
# Zkontrolujte oprávnění
ls -la registry/

# Zkontrolujte logy na chyby
python scripts/regular_phase_v5.3.py 2>&1 | grep -i error
```

### Import error?

```bash
# Přidejte do PYTHONPATH
export PYTHONPATH=/path/to/ai-log-analyzer:$PYTHONPATH
```

## Klíčové změny v5.3.1

1. **Report VŽDY** - i prázdný, i bez incidentů
2. **Registry append-only** - automatická evidence všeho
3. **Scope ≠ Propagation** - oddělené dataclasses
4. **Output dir** - reporty do `scripts/reports/`
