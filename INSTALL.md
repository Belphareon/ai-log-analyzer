# Instalace Incident Analysis Engine v5.2

## Struktura po instalaci

```
ai-log-analyzer/
├── scripts/
│   ├── v4/                          # Existující pipeline (beze změn)
│   │   ├── incident.py              # ← importuje se jako závislost
│   │   └── ...
│   ├── incident_analysis/           # ← NOVÉ: zkopírovat sem
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── analyzer.py
│   │   ├── timeline_builder.py
│   │   ├── causal_inference.py
│   │   ├── fix_recommender.py
│   │   ├── knowledge_base.py
│   │   ├── knowledge_matcher.py
│   │   └── formatter.py
│   └── analyze_incidents.py         # ← NOVÉ: zkopírovat sem
├── config/
│   └── known_issues/                # Existující, použije se jako knowledge base
│       ├── known_errors.yaml
│       └── known_peaks.yaml
└── ...
```

## Instalace

```bash
# 1. Rozbalit v5.2 balík
unzip incident_analysis_v5.2.zip

# 2. Zkopírovat modul do scripts/
cp -r incident_analysis_v5.2_package/incident_analysis/ ai-log-analyzer/scripts/

# 3. Zkopírovat CLI skript
cp incident_analysis_v5.2_package/analyze_incidents.py ai-log-analyzer/scripts/

# 4. Hotovo
```

## Použití

```bash
cd ai-log-analyzer/scripts

# 15min operational mode
python analyze_incidents.py --mode 15min --knowledge-dir ../config/known_issues

# Daily report
python analyze_incidents.py --mode daily --date 2026-01-22 --knowledge-dir ../config/known_issues

# S Slack notifikací
python analyze_incidents.py --mode 15min \
  --knowledge-dir ../config/known_issues \
  --slack-webhook $SLACK_WEBHOOK

# Triage report pro NEW incidenty
python analyze_incidents.py --mode 15min --triage --knowledge-dir ../config/known_issues
```

## Integrace do cronu

Přidat do `k8s/cronjob.yaml` nebo lokálního cronu:

```bash
# Každých 15 minut
*/15 * * * * cd /app/scripts && python analyze_incidents.py --mode 15min --knowledge-dir ../config/known_issues

# Daily report v 8:00
0 8 * * * cd /app/scripts && python analyze_incidents.py --mode daily --knowledge-dir ../config/known_issues
```

## Knowledge Base

Existující `config/known_issues/` se použije přímo. Formát je kompatibilní.

### known_errors.yaml

```yaml
- id: KE-001
  fingerprint: abc123def456
  category: DATABASE
  description: Order-service DB pool exhaustion
  affected_apps: [order-service]
  jira: OPS-431
  status: OPEN
  workaround: [Restart pod]
  error_pattern: "HikariPool.*Connection is not available"
```

### Přidání nového known error

1. Spustit s `--triage` → vygeneruje suggested YAML
2. Zkontrolovat a upravit
3. Přidat do `known_errors.yaml`
4. Další běhy už hlásí KNOWN

## Závislosti

Všechny závislosti už jsou v `requirements.txt`:
- psycopg2-binary
- python-dotenv
- requests
- pyyaml

## Poznámky

- `analyze_incidents.py` automaticky importuje z `v4/incident.py` (IncidentCollection)
- Konfigurace DB se načítá z `config/.env`
- Knowledge base cesta je relativní k working directory

