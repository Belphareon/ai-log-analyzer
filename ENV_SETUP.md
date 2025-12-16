# Environment Setup Guide

## 🔐 Správa credentials a konfigurace

Tento projekt používá **environment proměnné** pro všechna citlivá data (hesla, API klíče, atd.). Žádné credentials NEJSOU hardcoded v kódu.

---

## 📋 Quick Start

### 1. Zkopírujte template

```bash
cp .env.example .env
```

### 2. Upravte `.env` soubor

```bash
nano .env
# nebo
vim .env
# nebo použijte VS Code
code .env
```

### 3. Vyplňte své skutečné hodnoty

Minimálně potřebujete:
- `ES_URL` - URL vašeho Elasticsearch clusteru
- `ES_INDEX` - Pattern vašich indexů
- `ES_USER` - Technický účet z SMAX
- `ES_PASSWORD` - Heslo z SMAX emailu

---

## 🔒 Bezpečnost

### ✅ Co JE v gitu:
- `.env.example` - Template s příklady (BEZ reálných hesel)
- Všechny skripty vyžadují env proměnné

### ❌ Co NENÍ v gitu:
- `.env` - Váš lokální soubor s reálnými hesly
- Jakákoliv reálná credentials

**`.env` je v `.gitignore`** - nikdy se nenahraje do repositáře!

---

## 📝 Struktura `.env` souboru

### Minimální (Lightweight setup):

```bash
ES_URL=https://elasticsearch-prod.kb.cz:9200
ES_INDEX=cluster-app_pcb-*
ES_USER=XX_PCB_ES_READ
ES_PASSWORD=your_real_password_here
ES_VERIFY_CERTS=false
```

### Kompletní (Full setup):

```bash
# Elasticsearch
ES_URL=https://elasticsearch-prod.kb.cz:9200
ES_INDEX=cluster-app_pcb-*
ES_USER=XX_PCB_ES_READ
ES_PASSWORD=your_real_password_here
ES_VERIFY_CERTS=false

# Database
DATABASE_URL=postgresql://ailog:password@localhost:5432/ailog_analyzer
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog
DB_PASSWORD=your_db_password_here

# API
API_HOST=0.0.0.0
API_PORT=8000
SECRET_KEY=generated_secret_key_here

# Optional
OLLAMA_URL=http://localhost:11434
REDIS_URL=redis://localhost:6379
```

---

## 🚀 Načítání proměnných

### Python-dotenv (Automatické)

Všechny skripty používají:

```python
from dotenv import load_dotenv
import os

load_dotenv()  # Načte .env soubor

ES_PASSWORD = os.getenv('ES_PASSWORD')  # Získá hodnotu
```

### Ruční export (Alternativa)

Pokud nechcete používat `.env` soubor:

```bash
export ES_URL="https://elasticsearch-prod.kb.cz:9200"
export ES_INDEX="cluster-app_pcb-*"
export ES_USER="XX_PCB_ES_READ"
export ES_PASSWORD="your_password"
```

---

## 🔍 Troubleshooting

### Problem: "ES_PASSWORD is None"

**Příčina:** Proměnná není nastavená

**Řešení:**
```bash
# 1. Zkontrolujte, že máte .env soubor
ls -la .env

# 2. Zkontrolujte obsah
cat .env | grep ES_PASSWORD

# 3. Ujistěte se, že není prázdné
echo $ES_PASSWORD
```

### Problem: Skript stále hlásí chybějící heslo

**Řešení:**
```bash
# Načtěte .env manuálně před spuštěním
set -a
source .env
set +a

# Pak spusťte skript
python scripts/analyze_period.py ...
```

### Problem: `.env` byl omylem nahrán do gitu

**KRITICKÉ - Okamžitě:**
```bash
# 1. Odstraňte soubor z indexu
git rm --cached .env

# 2. Commit
git commit -m "security: Remove .env from git"

# 3. Push
git push

# 4. ZMĚŇTE VŠECHNA HESLA!
# Vaše credentials byly vystaveny v git historii
```

---

## 📚 Best Practices

### ✅ DO:
- Použijte `.env` pro lokální development
- V K8s použijte **Secrets** nebo **CyberArk**
- Pravidelně rotujte hesla
- Nikdy nesdílejte `.env` soubor
- Backup `.env` na bezpečném místě (ne v gitu!)

### ❌ DON'T:
- Nikdy necommitujte `.env` do gitu
- Nepošílejte hesla přes email/chat
- Nepište hesla do kódu
- Nenechávejte výchozí hodnoty v produkci

---

## 🎯 Pro různá prostředí

### Development (lokál)

```bash
.env              # Vaše vývojové credentials
```

### Testing

```bash
.env.test         # Test credentials
# Načtěte: load_dotenv('.env.test')
```

### Production (K8s)

```yaml
# Použijte K8s Secret místo .env
apiVersion: v1
kind: Secret
metadata:
  name: ai-log-analyzer-creds
type: Opaque
stringData:
  ES_USER: XX_PCB_ES_READ
  ES_PASSWORD: real_password_here
```

---

## 📞 Podpora

- **Zapomenuté heslo:** SMAX ticket pro reset
- **Nový tech účet:** [GETTING_STARTED.md](GETTING_STARTED.md) - Krok 1
- **ES přístup:** JIRA ticket PSLAS

---

**Poznámka:** Tento dokument je veřejný v gitu. NIKDY sem nepřidávejte reálná hesla nebo credentials!
