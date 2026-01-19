#!/bin/bash

# =============================================================================
# WORKFLOW MANAGER - Terminal-based workflow pro práci bez VS Code path issues
# =============================================================================

set -e

PROJECT_ROOT="/home/jvsete/git/sas/ai-log-analyzer"
PROGRESS_FILE="$PROJECT_ROOT/working_progress.md"

# Barvy pro output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# =============================================================================
# FUNKCE: Verifikace všech kritických skriptů
# =============================================================================
verify_scripts() {
    log_info "Ověřování dostupnosti kritických skriptů..."
    
    local scripts=(
        "analyze_period.py:Orchestration tool"
        "fetch_unlimited.py:Data fetcher"
        "trace_extractor.py:Trace extractor"
        "trace_report_detailed.py:Report generator"
    )
    
    local missing=0
    
    for script_info in "${scripts[@]}"; do
        IFS=':' read -r script desc <<< "$script_info"
        
        if [ -f "$PROJECT_ROOT/$script" ]; then
            log_success "Script dostupný: $script ($desc)"
        else
            log_error "Script CHYBÍ: $script ($desc)"
            missing=$((missing + 1))
        fi
    done
    
    if [ $missing -eq 0 ]; then
        log_success "Všechny kritické scripty jsou dostupné!"
        return 0
    else
        log_error "$missing scriptů chybí!"
        return 1
    fi
}

# =============================================================================
# FUNKCE: Verifikace konfigurace
# =============================================================================
verify_config() {
    log_info "Ověřování konfigurace..."
    
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        log_error ".env soubor chybí!"
        return 1
    fi
    
    local required_vars=("ES_HOST" "ES_USER" "ES_PASSWORD")
    local missing=0
    
    for var in "${required_vars[@]}"; do
        if grep -q "^${var}=" "$PROJECT_ROOT/.env"; then
            log_success "Proměnná $var je nastavena v .env"
        else
            log_error "Proměnná $var chybí v .env!"
            missing=$((missing + 1))
        fi
    done
    
    return $missing
}

# =============================================================================
# FUNKCE: Verifikace ES connectivity
# =============================================================================
verify_elasticsearch() {
    log_info "Testování připojení k Elasticsearch..."
    
    python3 << 'PYEOF'
import os
import requests
from requests.auth import HTTPBasicAuth
import sys

# Načti .env ručně
env_file = '/home/jvsete/git/sas/ai-log-analyzer/.env'
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

ES_HOST = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER')
ES_PASSWORD = os.getenv('ES_PASSWORD')

if not ES_USER or not ES_PASSWORD:
    print("❌ Credentials not found in .env")
    sys.exit(1)

try:
    auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    resp = requests.get(f"{ES_HOST}/_cluster/health", auth=auth, verify=False, timeout=10)
    
    if resp.status_code == 200:
        health = resp.json()
        print(f"✅ Elasticsearch is UP")
        print(f"   Status: {health.get('status')}")
        print(f"   Nodes: {health.get('number_of_nodes')}")
        sys.exit(0)
    else:
        print(f"❌ Status {resp.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
PYEOF
}

# =============================================================================
# FUNKCE: Test orchestračního nástroje
# =============================================================================
test_orchestration() {
    log_info "Testování orchestračního nástroje analyze_period.py..."
    
    cd "$PROJECT_ROOT"
    
    FROM="2025-12-03T09:00:00Z"
    TO="2025-12-03T09:15:00Z"
    OUTPUT="test_orchestration_$(date +%s).json"
    
    log_info "Parametry: --from $FROM --to $TO --output $OUTPUT"
    
    if python3 analyze_period.py --from "$FROM" --to "$TO" --output "$OUTPUT" 2>&1 | tee /tmp/test_orchestration.log; then
        log_success "Orchestrační nástroj funguje správně!"
        
        if [ -f "$OUTPUT" ]; then
            SIZE=$(du -h "$OUTPUT" | cut -f1)
            LINES=$(wc -l < "$OUTPUT")
            log_success "Output soubor: $OUTPUT ($SIZE, $LINES řádků)"
            
            if python3 -c "import json; json.load(open('$OUTPUT'))" 2>/dev/null; then
                log_success "JSON struktura je validní"
                return 0
            else
                log_error "JSON struktura není validní!"
                return 1
            fi
        else
            log_error "Output soubor nebyl vytvořen!"
            return 1
        fi
    else
        log_error "Orchestrační nástroj selhal!"
        cat /tmp/test_orchestration.log
        return 1
    fi
}

# =============================================================================
# HLAVNÍ WORKFLOW
# =============================================================================
main() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   AI Log Analyzer - System Verification Workflow         ║${NC}"
    echo -e "${BLUE}║   $(date '+%Y-%m-%d %H:%M:%S UTC')                              ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    
    # Step 1: Verify scripts exist
    echo -e "\n${BLUE}STEP 1: Ověřování dostupnosti skriptů${NC}"
    if ! verify_scripts; then
        log_error "Chybí kritické scripty!"
        return 1
    fi
    
    # Step 2: Verify configuration
    echo -e "\n${BLUE}STEP 2: Ověřování konfigurace${NC}"
    if ! verify_config; then
        log_error "Konfigurace je neúplná!"
        return 1
    fi
    
    # Step 3: Test Elasticsearch
    echo -e "\n${BLUE}STEP 3: Testování Elasticsearch${NC}"
    if ! verify_elasticsearch; then
        log_error "Nelze se připojit k Elasticsearch!"
        return 1
    fi
    
    # Step 4: Test orchestration tool
    echo -e "\n${BLUE}STEP 4: Testování orchestračního nástroje${NC}"
    if ! test_orchestration; then
        log_error "Orchestrační nástroj nefunguje!"
        return 1
    fi
    
    # Step 5: Success
    echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   ✅ VŠECHNY TESTY USPĚLY - SYSTÉM JE PŘIPRAVEN         ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    
    return 0
}

# Spustit
main "$@"
exit $?
