#!/bin/bash
#
# publish_daily_reports.sh - Publikuj denní reporty do Teams a Confluence
#
# Spustí se po backfill a:
# 1. Vygeneruje daily report
# 2. Pošle do Teams
# 3. Uploadne tabulky do Confluence (pomocí ito-upload)
#
# Vyžaduje:
#   - /root/git/toolbox/ITO-sync-v4/ito-upload (binární)
#   - CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN v environment
#
# Použití:
#   ./publish_daily_reports.sh
#   ./publish_daily_reports.sh --dry-run
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [ -f "$REPO_DIR/.env" ]; then
    export $(grep -v '^#' "$REPO_DIR/.env" | xargs)
fi

DRY_RUN=${1:-}

# Cesta k ito-upload
ITO_UPLOAD="/root/git/toolbox/ITO-sync-v4/ito-upload"

echo "========================================================================"
echo "📊 PUBLISHING DAILY REPORTS"
echo "========================================================================"
echo ""

# ========================================================================
# 1. Generate Daily Report from Backfill Log
# ========================================================================
echo "📋 Step 1: Generate Daily Report..."

REPORTS_DIR="$SCRIPT_DIR/reports"
LATEST_REPORT=$(find "$REPORTS_DIR" -name "problem_report_*.json" -type f 2>/dev/null | sort -r | head -1)

if [ -z "$LATEST_REPORT" ]; then
    echo "⚠️ No recent backfill report found"
    echo "   Looking in: $REPORTS_DIR"
    echo "   (This is OK if backfill hasn't run yet)"
    LATEST_REPORT=""
else
    echo "   Found: $LATEST_REPORT"
fi

# Prepare log file (if available)
LOG_FILE=""
if [ -n "$LATEST_REPORT" ]; then
    # JSON reports jsou jiného formátu - budeme je parsovat jinak
    echo "   Using: $(basename "$LATEST_REPORT")"
fi

# ========================================================================
# 2. Send Daily Report to Teams (if configured)
# ========================================================================
echo ""
echo "📢 Step 2: Send to Teams..."

if [ -z "$TEAMS_WEBHOOK_URL" ]; then
    echo "   ⚠️ TEAMS_WEBHOOK_URL not configured, skipping"
else
    python3 "$SCRIPT_DIR/daily_report_generator.py" \
        --output "$SCRIPT_DIR/reports" \
        --confluence-link "https://confluence.kb.cz/pages/viewpage.action?pageId=$CONFLUENCE_DAILY_REPORT_PAGE_ID" \
        --send-teams 2>/dev/null || echo "   ⚠️ Failed to send Teams notification"
fi

# ========================================================================
# 3. Publish Tables to Confluence (using ito-upload)
# ========================================================================
echo ""
echo "📤 Step 3: Publish to Confluence..."

# Check prerequisites
if [ ! -f "$ITO_UPLOAD" ]; then
    echo "   ❌ ito-upload not found at $ITO_UPLOAD"
    echo "   Install it: cd /root/git/toolbox/ITO-sync-v4 && go build -o ito-upload ito-upload-main.go csv-to-confluence.go logger.go variables.go"
    exit 1
fi

if [ -z "$CONFLUENCE_USERNAME" ] || [ -z "$CONFLUENCE_API_TOKEN" ]; then
    echo "   ⚠️ Missing CONFLUENCE_USERNAME or CONFLUENCE_API_TOKEN"
    echo "   Set them: export CONFLUENCE_USERNAME=... && export CONFLUENCE_API_TOKEN=..."
    exit 1
fi

# Upload Known Errors
echo "   Publishing Known Errors..."
ERRORS_CSV="$SCRIPT_DIR/exports/latest/errors_table.csv"
if [ ! -f "$ERRORS_CSV" ]; then
    echo "   ⚠️ CSV not found: $ERRORS_CSV (backfill may not have run yet)"
else
    if [ -z "$DRY_RUN" ]; then
        if "$ITO_UPLOAD" \
            --file "$ERRORS_CSV" \
            --page-id "$CONFLUENCE_KNOWN_ERRORS_PAGE_ID" \
            --title "Known Errors - Last 24h"; then
            echo "   ✅ Known Errors published"
        else
            ERROR_CODE=$?
            echo "   ❌ Failed to publish Known Errors (exit code: $ERROR_CODE)"
        fi
    else
        echo "   [DRY-RUN] Would upload: $ERRORS_CSV → Page $CONFLUENCE_KNOWN_ERRORS_PAGE_ID"
    fi
fi

# Upload Known Peaks
echo "   Publishing Known Peaks..."
PEAKS_CSV="$SCRIPT_DIR/exports/latest/peaks_table.csv"
if [ ! -f "$PEAKS_CSV" ]; then
    echo "   ⚠️ CSV not found: $PEAKS_CSV (backfill may not have run yet)"
else
    if [ -z "$DRY_RUN" ]; then
        if "$ITO_UPLOAD" \
            --file "$PEAKS_CSV" \
            --page-id "$CONFLUENCE_KNOWN_PEAKS_PAGE_ID" \
            --title "Known Peaks - Last 24h"; then
            echo "   ✅ Known Peaks published"
        else
            ERROR_CODE=$?
            echo "   ❌ Failed to publish Known Peaks (exit code: $ERROR_CODE)"
        fi
    else
        echo "   [DRY-RUN] Would upload: $PEAKS_CSV → Page $CONFLUENCE_KNOWN_PEAKS_PAGE_ID"
    fi
fi

# Upload Recent Incidents (from daily incident analysis report)
echo "   Publishing Recent Incidents (Daily Analysis)..."
if [ -z "$DRY_RUN" ]; then
    if python3 "$SCRIPT_DIR/recent_incidents_publisher.py"; then
        echo "   ✅ Recent Incidents published"
    else
        ERROR_CODE=$?
        echo "   ⚠️ Failed to publish Recent Incidents (non-critical)"
    fi
else
    echo "   [DRY-RUN] Would publish daily incident analysis report"
fi

echo ""
echo "========================================================================"
echo "✅ PUBLISHING COMPLETE"
echo "========================================================================"
echo ""
