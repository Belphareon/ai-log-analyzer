#!/bin/bash
# ============================================================================
# AI Log Analyzer - REGULAR Phase Runner
# ============================================================================
# Spouští REGULAR fázi - každých 15 minut
#
# Použití:
#   ./run_regular.sh
#   ./run_regular.sh --output data/reports/
#   ./run_regular.sh --quiet  # pro cron
#
# Cron setup:
#   */15 * * * * /path/to/run_regular.sh --quiet >> /var/log/ailog/cron.log 2>&1
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
OUTPUT=""
QUIET=""
DRY_RUN=""
DATE_FROM=""
DATE_TO=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --output)
            OUTPUT="--output $2"
            shift 2
            ;;
        --quiet)
            QUIET="--quiet"
            shift
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --from)
            DATE_FROM="--from $2"
            shift 2
            ;;
        --to)
            DATE_TO="--to $2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --output DIR    Output directory for reports"
            echo "  --quiet         Minimal output (for cron)"
            echo "  --dry-run       Dry run - no DB writes"
            echo "  --from DATE     Start time (ISO format)"
            echo "  --to DATE       End time (ISO format)"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build command
CMD="python scripts/regular_phase.py $OUTPUT $QUIET $DRY_RUN $DATE_FROM $DATE_TO"

if [ -z "$QUIET" ]; then
    echo "=============================================="
    echo "🚀 AI Log Analyzer - REGULAR Phase"
    echo "   $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=============================================="
    echo ""
    echo "Running: $CMD"
    echo ""
fi

# Run
eval $CMD
EXIT_CODE=$?

if [ -z "$QUIET" ]; then
    echo ""
    echo "=============================================="
    if [ $EXIT_CODE -eq 0 ]; then
        echo "✅ REGULAR Phase complete"
    else
        echo "❌ REGULAR Phase failed with code $EXIT_CODE"
    fi
    echo "=============================================="
fi

exit $EXIT_CODE
