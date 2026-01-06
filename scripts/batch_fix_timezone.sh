#!/bin/bash
#
# Batch fix all peak_fixed_*.txt files in /tmp
# Shifts all times by +1 hour (UTC -> CET)
#

cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate

echo "========================================"
echo "🕐 Batch Timezone Fix"
echo "========================================"
echo ""

FILES=(
    /tmp/peak_fixed_2025_12_01.txt
    /tmp/peak_fixed_2025_12_02_03.txt
    /tmp/peak_fixed_2025_12_04_05.txt
    /tmp/peak_fixed_2025_12_06_07.txt
    /tmp/peak_fixed_2025_12_08_09.txt
    /tmp/peak_fixed_2025_12_10_11.txt
    /tmp/peak_fixed_2025_12_12_13.txt
    /tmp/peak_fixed_2025_12_14_15.txt
    /tmp/peak_fixed_2025_12_16.txt
)

TOTAL=${#FILES[@]}
SUCCESS=0
FAILED=0

for FILE in "${FILES[@]}"; do
    if [ -f "$FILE" ]; then
        echo "Processing: $FILE"
        
        # Backup original
        cp "$FILE" "${FILE}.backup_before_timezone_fix"
        
        # Fix timezone (overwrite original)
        python scripts/fix_timezone_in_txt.py --input "$FILE" --output "$FILE"
        
        if [ $? -eq 0 ]; then
            ((SUCCESS++))
            echo "✅ Fixed: $FILE"
        else
            ((FAILED++))
            echo "❌ Failed: $FILE"
            # Restore backup
            mv "${FILE}.backup_before_timezone_fix" "$FILE"
        fi
        
        echo ""
    else
        echo "⚠️  File not found: $FILE"
        ((FAILED++))
        echo ""
    fi
done

echo "========================================"
echo "📊 Summary:"
echo "   Total files: $TOTAL"
echo "   Success: $SUCCESS"
echo "   Failed: $FAILED"
echo "========================================"
echo ""
echo "✅ Backups saved as: *.backup_before_timezone_fix"
echo ""
