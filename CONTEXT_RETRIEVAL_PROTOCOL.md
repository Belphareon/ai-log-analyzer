# 📋 CONTEXT RETRIEVAL PROTOCOL
## AI Log Analyzer - Quick Reference

**Verze:** 2.5 | **Updated:** 2026-01-12 | **Phase:** 5B (INIT Phase 3 Weeks)

---

## � KEY LINKS

| Need | Location |
|------|----------|
| **Full Setup Guide** | [GETTING_STARTED.md](GETTING_STARTED.md) |
| **Session Progress** | [working_progress.md](working_progress.md) |
| **All Scripts** | [scripts/INDEX.md](scripts/INDEX.md) |
| **Project Overview** | [README.md](README.md) |

## 📌 CURRENT STATE

- **Database:** P050TD01.DEV.KB.CZ:5432/ailog_analyzer
- **Status:** INIT Phase 3 Weeks in progress (1-21.12.2025)
- **Next:** Execute INIT ingestion → fill grid → Regular Phase with peak detection

### Architecture: Two-Phase Mandatory

| Phase | Purpose | Data | Peak Detection |
|-------|---------|------|-----------------|
| **INIT** | 3 weeks baseline | 21 days | NO (aggregation only) |
| **REGULAR** | Daily ingestion | Today+ | YES (ratio >= 15×) |

**Why 3 Weeks?** Peak detection compares same day-of-week across weeks (Mon vs Mon, not Mon vs Fri)

---

## 📂 Workspace Structure

```
ai-log-analyzer/
├── CONTEXT_RETRIEVAL_PROTOCOL.md  ← You are here
├── GETTING_STARTED.md             ← Complete instructions
├── working_progress.md             ← Session log + tasks
├── README.md                       ← Project overview
├── scripts/
│   ├── INDEX.md                    ← Script reference
│   ├── ingest_from_log_v2.py       ← MAIN: INIT + peak detection
│   ├── fill_missing_windows.py     ← Complete grid
│   ├── collect_peak_detailed.py    ← Collect from ES
│   └── ...
└── app/ alembic/ _archive_* ...
```

---

## � QUICK DATABASE OPERATIONS

### Check DB State
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
python3 << 'EOF'
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) as rows, COUNT(DISTINCT day_of_week) as days FROM peak_statistics;")
r = cursor.fetchone()
print(f"✅ Rows: {r[0]}, Days: {r[1]}")
EOF
```

### Data Operations (Python)
```python
from dotenv import load_dotenv
import psycopg2, os
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
```

### DDL Operations (Python)
```python
# Use DDL user and SET ROLE!
cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
# Now safe to CREATE/ALTER/GRANT
```

---

### peak_statistics
```sql
day_of_week INT (0-6)
hour_of_day INT (0-23)
quarter_hour INT (0-3)
namespace VARCHAR
mean_errors FLOAT
stddev_errors FLOAT
samples_count INT
PRIMARY KEY (day_of_week, hour_of_day, quarter_hour, namespace)
```

### peak_investigation
```sql
Same key as above + original_value, reference_value, ratio, etc.
```

---

## ⚠️ CRITICAL POINTS

**Why 3 Weeks?** Peak detection needs 3 data points per day-of-week (Monday vs Monday, not Monday vs Friday)

**Why Same-Day?** Compares -15, -30, -45 min windows on SAME day, not cross-day

**Why Replacement?** Skipping peaks breaks continuity; we replace with reference value and log anomalies separately

---

### INIT Phase (3 Weeks)
```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

# Step 1: Setup DB (one-time)
python3 setup_peak_db.py
python3 grant_permissions.py

# Step 2: Ingest all 14 files (1-21.12)
for file in /tmp/peak_fixed_2025_12_*.txt; do
  python3 ingest_from_log_v2.py --init "$file"
done

# Step 3: Fill missing windows
python3 fill_missing_windows.py

# Expected result: 24,192 rows (21 × 96 × 12)
```

### REGULAR Phase (After INIT complete)
```bash
# Daily: ingest yesterday's data with peak detection
python3 ingest_from_log_v2.py --input /tmp/peak_fixed_2025_12_22.txt
```

---

**Version:** 2.5 | **Last Updated:** 2026-01-12

