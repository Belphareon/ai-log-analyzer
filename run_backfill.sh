#!/bin/bash
# ============================================================================
# AI Log Analyzer - BACKFILL Runner
# ============================================================================
# Zpracuje historická data S peak detection
#
# Použití:
#   ./run_backfill.sh --days 14
#   ./run_backfill.sh --from "2026-01-06" --to "2026-01-20"
#   ./run_backfill.sh --days 14 --output data/reports/
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
elif [ -f config/.env ]; then
    export $(grep -v '^#' config/.env | xargs)
fi

# Default values
DAYS=14
OUTPUT=""
DRY_RUN=""
DATE_FROM=""
DATE_TO=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days)
            DAYS="$2"
            shift 2
            ;;
        --from)
            DATE_FROM="$2"
            shift 2
            ;;
        --to)
            DATE_TO="$2"
            shift 2
            ;;
        --output)
            OUTPUT="--output $2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --days N        Number of days to backfill (default: 14)"
            echo "  --from DATE     Start date (ISO format or YYYY-MM-DD)"
            echo "  --to DATE       End date (ISO format or YYYY-MM-DD)"
            echo "  --output DIR    Output directory for reports"
            echo "  --dry-run       Dry run - no DB writes"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "🔄 AI Log Analyzer - BACKFILL"
echo "   $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="
echo ""

# Build command
CMD="python scripts/backfill_v6.py"

if [ -n "$DATE_FROM" ] && [ -n "$DATE_TO" ]; then
    CMD="$CMD --from '$DATE_FROM' --to '$DATE_TO'"
else
    CMD="$CMD --days $DAYS"
fi

if [ -n "$OUTPUT" ]; then
    CMD="$CMD $OUTPUT"
fi

if [ -n "$DRY_RUN" ]; then
    CMD="$CMD $DRY_RUN"
fi

echo "Running: $CMD"
echo ""

# Run
eval $CMD

echo ""
echo "=============================================="
echo "✅ BACKFILL complete"
echo "=============================================="
