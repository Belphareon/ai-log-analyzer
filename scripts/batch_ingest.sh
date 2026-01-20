#!/bin/bash
#
# Batch Ingestion Script - INIT + REGULAR phases
#
# INIT Phase: Load historical data from local files (no peak detection)
# REGULAR Phase: Fetch from ES with peak detection + intelligent analysis
#
# Usage:
#   ./batch_ingest.sh --init          # Run INIT phase only (Dec 2025)
#   ./batch_ingest.sh --regular       # Run REGULAR phase only (Jan 2026)
#   ./batch_ingest.sh --all           # Run both phases
#   ./batch_ingest.sh --regular --from 2026-01-10  # Start REGULAR from specific date
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCAL_DATA_DIR="/tmp/ai-log-data"
TMP_DIR="/tmp"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# Default values
RUN_INIT=false
RUN_REGULAR=false
REGULAR_FROM=""
REGULAR_TO=""
DRY_RUN=false
SKIP_EXISTING=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --init)
            RUN_INIT=true
            shift
            ;;
        --regular)
            RUN_REGULAR=true
            shift
            ;;
        --all)
            RUN_INIT=true
            RUN_REGULAR=true
            shift
            ;;
        --from)
            REGULAR_FROM="$2"
            shift 2
            ;;
        --to)
            REGULAR_TO="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            SKIP_EXISTING=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --init          Run INIT phase (Dec 2025 from local files)"
            echo "  --regular       Run REGULAR phase (Jan 2026 from ES)"
            echo "  --all           Run both phases"
            echo "  --from DATE     Start REGULAR from date (YYYY-MM-DD)"
            echo "  --to DATE       End REGULAR at date (YYYY-MM-DD, default: yesterday)"
            echo "  --dry-run       Show what would be done without executing"
            echo "  --force         Don't skip existing days in DB"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ "$RUN_INIT" == "false" && "$RUN_REGULAR" == "false" ]]; then
    log_error "Specify --init, --regular, or --all"
    exit 1
fi

cd "$PROJECT_DIR"

echo "========================================"
echo "🔄 BATCH INGESTION SCRIPT"
echo "========================================"
echo "Project: $PROJECT_DIR"
echo "Local data: $LOCAL_DATA_DIR"
echo "Init phase: $RUN_INIT"
echo "Regular phase: $RUN_REGULAR"
echo "Dry run: $DRY_RUN"
echo "========================================"
echo ""

# Counters
INIT_SUCCESS=0
INIT_FAILED=0
INIT_SKIPPED=0
REGULAR_SUCCESS=0
REGULAR_FAILED=0
REGULAR_SKIPPED=0
PEAKS_DETECTED=0

#
# INIT PHASE - December 2025 from local CONVERTED files
#
run_init_phase() {
    log_info "========== INIT PHASE (December 2025) =========="
    log_info "Loading baseline data from CONVERTED files (with DATA|TIMESTAMP format)..."
    echo ""
    
    # Use CONVERTED files which have proper DATA|TIMESTAMP|... format
    # These were converted from old human-readable format
    INIT_FILES=(
        # Individual day files
        "peak_fixed_2025_12_01_CONVERTED.txt"
        # Multi-day files
        "peak_fixed_2025_12_02_03_CONVERTED.txt"
        "peak_fixed_2025_12_04_05_CONVERTED.txt"
        "peak_fixed_2025_12_06_07_CONVERTED.txt"
        "peak_fixed_2025_12_08_09_CONVERTED.txt"
        "peak_fixed_2025_12_10_11_CONVERTED.txt"
        "peak_fixed_2025_12_12_13_CONVERTED.txt"
        "peak_fixed_2025_12_14_15_CONVERTED.txt"
        # Individual day files (after multi-day)
        "peak_fixed_2025_12_16_CONVERTED.txt"
        "peak_fixed_2025_12_17_CONVERTED.txt"
        "peak_fixed_2025_12_18_CONVERTED.txt"
        "peak_fixed_2025_12_19_CONVERTED.txt"
        "peak_fixed_2025_12_20_CONVERTED.txt"
        "peak_fixed_2025_12_21_CONVERTED.txt"
        "peak_fixed_2025_12_22_CONVERTED.txt"
        "peak_fixed_2025_12_23_CONVERTED.txt"
        "peak_fixed_2025_12_24_CONVERTED.txt"
        "peak_fixed_2025_12_25_CONVERTED.txt"
        "peak_fixed_2025_12_26_CONVERTED.txt"
        "peak_fixed_2025_12_27_CONVERTED.txt"
        "peak_fixed_2025_12_28_CONVERTED.txt"
        "peak_fixed_2025_12_29_CONVERTED.txt"
        "peak_fixed_2025_12_30_CONVERTED.txt"
        "peak_fixed_2025_12_31_CONVERTED.txt"
    )
    
    total=${#INIT_FILES[@]}
    current=0
    
    for filename in "${INIT_FILES[@]}"; do
        current=$((current + 1))
        input_file="$LOCAL_DATA_DIR/$filename"
        
        echo -n "[$current/$total] $filename: "
        
        # Check if file exists
        if [[ ! -f "$input_file" ]]; then
            log_warn "File not found - SKIPPED"
            INIT_SKIPPED=$((INIT_SKIPPED + 1))
            continue
        fi
        
        # Count DATA rows in file
        data_rows=$(grep -c "^DATA|" "$input_file" 2>/dev/null || echo "0")
        
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "🔵 DRY RUN: Would ingest $data_rows DATA rows (--init mode)"
            INIT_SUCCESS=$((INIT_SUCCESS + 1))
            continue
        fi
        
        # Run ingestion in INIT mode (no peak detection)
        if python3 scripts/ingest_from_log_v2.py --init --input "$input_file" > /tmp/ingest_$(basename "$filename" .txt).log 2>&1; then
            log_success "Ingested $data_rows rows"
            INIT_SUCCESS=$((INIT_SUCCESS + 1))
        else
            log_error "FAILED - see /tmp/ingest_$(basename "$filename" .txt).log"
            INIT_FAILED=$((INIT_FAILED + 1))
        fi
        
        # Small delay to avoid overwhelming DB
        sleep 1
    done
    
    echo ""
    log_info "INIT PHASE SUMMARY:"
    log_info "  ✅ Success: $INIT_SUCCESS"
    log_info "  ⏭️  Skipped: $INIT_SKIPPED"
    log_info "  ❌ Failed: $INIT_FAILED"
    echo ""
    
    # Post-INIT processing (only if not dry run and there were successful ingestions)
    if [[ "$DRY_RUN" != "true" && "$INIT_SUCCESS" -gt 0 ]]; then
        log_info "========== POST-INIT PROCESSING =========="
        echo ""
        
        # 1. Fill missing windows with zeros
        log_info "Step 1: Filling missing time windows with zeros..."
        if python3 scripts/fill_missing_windows_fast.py 2>&1 | tail -5; then
            log_success "Missing windows filled successfully"
        else
            log_warn "Fill missing windows completed with warnings (check output above)"
        fi
        echo ""
        
        # 2. Calculate aggregation baseline
        log_info "Step 2: Calculating aggregation baseline..."
        if python3 scripts/calculate_aggregation_baseline.py 2>&1 | tail -5; then
            log_success "Aggregation baseline calculated successfully"
        else
            log_warn "Aggregation calculation completed with warnings"
        fi
        echo ""
        
        log_info "POST-INIT PROCESSING COMPLETE"
    fi
}

#
# REGULAR PHASE - January 2026 from ES
#
run_regular_phase() {
    log_info "========== REGULAR PHASE (January 2026) =========="
    log_info "Fetching data from ES with peak detection + intelligent analysis..."
    echo ""
    
    # Determine date range
    if [[ -z "$REGULAR_FROM" ]]; then
        REGULAR_FROM="2026-01-01"
    fi
    
    if [[ -z "$REGULAR_TO" ]]; then
        # Default: yesterday
        REGULAR_TO=$(date -d "yesterday" +%Y-%m-%d)
    fi
    
    log_info "Date range: $REGULAR_FROM to $REGULAR_TO"
    echo ""
    
    # Generate date list
    current_date="$REGULAR_FROM"
    end_date="$REGULAR_TO"
    
    while [[ "$current_date" < "$end_date" || "$current_date" == "$end_date" ]]; do
        dates+=("$current_date")
        current_date=$(date -d "$current_date + 1 day" +%Y-%m-%d)
    done
    
    total=${#dates[@]}
    current=0
    
    for date in "${dates[@]}"; do
        current=$((current + 1))
        next_date=$(date -d "$date + 1 day" +%Y-%m-%d)
        
        echo -n "[$current/$total] $date: "
        
        # Check if already in DB
        if [[ "$SKIP_EXISTING" == "true" ]]; then
            count=$(python3 -c "
import psycopg2
from dotenv import load_dotenv
import os
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM ailog_peak.peak_raw_data WHERE DATE(timestamp) = %s\", ('$date',))
print(cur.fetchone()[0])
conn.close()
" 2>/dev/null || echo "0")
            
            if [[ "$count" -gt 0 ]]; then
                echo "⏭️  SKIPPED (already $count rows in DB)"
                REGULAR_SKIPPED=$((REGULAR_SKIPPED + 1))
                continue
            fi
        fi
        
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "🔵 DRY RUN: Would run pipeline for $date"
            REGULAR_SUCCESS=$((REGULAR_SUCCESS + 1))
            continue
        fi
        
        # Run full pipeline for this day
        from_ts="${date}T00:00:00Z"
        to_ts="${next_date}T00:00:00Z"
        
        log_file="/tmp/pipeline_${date//-/_}.log"
        
        echo ""
        log_info "Running pipeline: $from_ts → $to_ts"
        
        if python3 scripts/run_pipeline.py --from "$from_ts" --to "$to_ts" 2>&1 | tee "$log_file"; then
            # Count peaks detected
            day_peaks=$(grep -c "PEAK DETECTED" "$log_file" 2>/dev/null || echo "0")
            PEAKS_DETECTED=$((PEAKS_DETECTED + day_peaks))
            
            log_success "Day $date completed (peaks: $day_peaks)"
            REGULAR_SUCCESS=$((REGULAR_SUCCESS + 1))
        else
            log_error "Day $date FAILED - see $log_file"
            REGULAR_FAILED=$((REGULAR_FAILED + 1))
        fi
        
        echo ""
        # Delay between days to avoid ES rate limits
        sleep 5
    done
    
    echo ""
    log_info "REGULAR PHASE SUMMARY:"
    log_info "  ✅ Success: $REGULAR_SUCCESS"
    log_info "  ⏭️  Skipped: $REGULAR_SKIPPED"
    log_info "  ❌ Failed: $REGULAR_FAILED"
    log_info "  🔴 Peaks detected: $PEAKS_DETECTED"
    echo ""
}

#
# MAIN
#

if [[ "$RUN_INIT" == "true" ]]; then
    run_init_phase
fi

if [[ "$RUN_REGULAR" == "true" ]]; then
    run_regular_phase
fi

echo "========================================"
echo "🏁 BATCH INGESTION COMPLETE"
echo "========================================"
echo "INIT:    $INIT_SUCCESS success, $INIT_SKIPPED skipped, $INIT_FAILED failed"
echo "REGULAR: $REGULAR_SUCCESS success, $REGULAR_SKIPPED skipped, $REGULAR_FAILED failed"
echo "PEAKS:   $PEAKS_DETECTED total detected"
echo "========================================"
