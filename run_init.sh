#!/bin/bash
# ============================================================================
# AI Log Analyzer - INIT Phase Runner
# ============================================================================
# Spouští INIT fázi - sběr baseline dat (21+ dní)
#
# Použití:
#   ./run_init.sh --days 21
#   ./run_init.sh --from "2025-12-01T00:00:00Z" --to "2025-12-21T23:59:59Z"
#   ./run_init.sh --days 21 --dry-run
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
DAYS=21
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
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --days N        Number of days to collect (default: 21)"
            echo "  --from DATE     Start date (ISO format)"
            echo "  --to DATE       End date (ISO format)"
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
echo "🚀 AI Log Analyzer - INIT Phase"
echo "=============================================="
echo ""

# Build command
CMD="python scripts/init_phase.py"

if [ -n "$DATE_FROM" ] && [ -n "$DATE_TO" ]; then
    CMD="$CMD --from '$DATE_FROM' --to '$DATE_TO'"
else
    CMD="$CMD --days $DAYS"
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
echo "✅ INIT Phase complete"
echo ""
echo "Next steps:"
echo "  1. Calculate thresholds:"
echo "     python scripts/core/calculate_peak_thresholds.py"
echo ""
echo "  2. Run backfill:"
echo "     ./run_backfill.sh --days 14"
echo ""
echo "  3. Setup cron for regular phase:"
echo "     */15 * * * * $SCRIPT_DIR/run_regular.sh --quiet"
echo "=============================================="
