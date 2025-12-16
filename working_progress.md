# 🔄 Working Progress - AI Log Analyzer (AKTUÁLNÍ)

**Projekt:** AI Log Analyzer - Phase 5A (Data Ingestion)  
**Poslední update:** 2025-12-16 12:35 UTC  
**Status:** ⏳ COLLECTING DATA - PID 14077 RUNNING

---

## 📊 CURRENT STATUS

### ✅ COMPLETED TODAY

| Task | Status | Time |
|------|--------|------|
| Smazat testovací data z DB | ✅ | 12:05 |
| Vytvořit `ingest_from_log.py` | ✅ | 12:10 |
| Aktualizovat `scripts/INDEX.md` | ✅ | 12:20 |
| Spustit sbírání 2025-12-01 | ⏳ | PID 14077 |

### 🔄 CURRENTLY RUNNING (NE RUŠIT!)

```
Terminal 1:
  PID:     14077
  Command: collect_peak_detailed.py --from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"
  Output:  /tmp/peak_full_2025_12_01.txt
  Status:  ⏳ COLLECTING (ETA: 2-3 min)
```

### 📋 TODO NEXT

```
1. [ ] Počkat na dokončení PID 14077 (NE RUŠIT!)
2. [ ] Nahrát do DB: ingest_from_log.py --input /tmp/peak_full_2025_12_01.txt
3. [ ] Ověřit: SELECT COUNT(*) FROM peak_statistics (expect ~848 rows)

4. [ ] SBÍRÁNÍ PO 2 DNECH (Sequential):
       [ ] 2025-12-02 & 2025-12-03
       [ ] 2025-12-04 & 2025-12-05
       [ ] 2025-12-06 & 2025-12-07
       [ ] 2025-12-08 & 2025-12-09
       [ ] 2025-12-10 & 2025-12-11
       [ ] 2025-12-12 & 2025-12-13
       [ ] 2025-12-14 & 2025-12-15
       [ ] 2025-12-16 (TODAY)

5. [ ] FINAL: Ověřit DB (all 16 days, ~13,568 rows)
```

---

## 💾 DATA FILES

| File | Status | Notes |
|------|--------|-------|
| `/tmp/peak_full_2025_12_01.txt` | ⏳ COLLECTING | PID 14077 - NE RUŠIT! |
| `/tmp/peak_full_2025_12_02.txt` | 📋 TODO | |
| ... | 📋 TODO | |
| `/tmp/peak_full_2025_12_16.txt` | 📋 TODO | |

---

## 🚨 PRAVIDLA

⚠️ **NE RUŠIT BĚŽÍCÍ PROCES** - Sbírání trvá minuty!  
⚠️ **VŽDYCKY EXPLICIT DATES** - `--from "2025-12-XXT00:00:00Z" --to "2025-12-YYT00:00:00Z"`  
⚠️ **Z SUFFIX** - Elasticsearch potřebuje Z, ne +00:00  
⚠️ **PRACUJ V JINÉM TERMINÁLU** - Nech sbírání na pokoji  

---

## 🔑 KEY INFO

**DB:**
- Host: P050TD01.DEV.KB.CZ:5432
- DB: ailog_analyzer
- Table: ailog_peak.peak_statistics
- Current rows: 5 (bude ~13,568 po nahrání všech 16 dní)

**Scripts:**
- `collect_peak_detailed.py` - sbírá data z ES
- `ingest_from_log.py` - nahrává do DB
- `scripts/INDEX.md` - dokumentace

**Archiv starších logů:** `_archive_md/COMPLETED_LOG_2025_12_16.md`
