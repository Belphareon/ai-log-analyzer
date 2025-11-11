# Work Plan - ML-based Trends Analysis

## 🎯 CÍLE:
1. Weekly error analysis z ES
2. ML pattern detection (opakující se vs nové)
3. Known issues list (problémy k fixnutí)
4. Peak detection algorithm

## 📋 KROKY:
- [x] Základní trends endpoint
- [ ] Schema pro weekly report
- [ ] ES data fetcher (7 dní)
- [ ] Pattern clustering (sklearn)
- [ ] Known issues tracking v DB
- [ ] Peak detector
- [ ] Test na reálných datech

## 💾 DATABÁZE:
Přidat tabulku: known_issues
- fingerprint (pattern ID)
- error_code
- count_total
- first_seen
- last_seen
- status (new/recurring/fixed)

## ✅ PROGRESS UPDATE:
- [x] Schema pro trends vytvořeno
- [x] Pattern detector service (normalizace, clustering)
- [x] Weekly trends endpoint implementován
- [ ] Test probíhá...

## �� CO DĚLÁ ENDPOINT:
1. Fetchuje errory z posledních N dní z ES
2. Normalizuje messages (odstraní IDs, UUIDs, timestamps)
3. Clusteruje podobné errory
4. Identifikuje recurring vs new patterns
5. Vytváří known_issues list (>10 výskytů)
6. Generuje recommendations

