#!/bin/bash
# Batch ingest all peak data files using SIMPLE INIT
echo "====== BATCH INGEST ALL DATA FILES ======"
echo "Mode: SIMPLE INIT (no peak detection)"
echo ""

cd ~/git/sas/ai-log-analyzer/scripts
source ../.venv/bin/activate

# Clear DB
echo "🗑️  Clearing DB..."
python clear_peak_db.py
echo ""

# Get list of files in order
files=(
  /tmp/peak_fixed_2025_12_01.txt
  /tmp/peak_fixed_2025_12_02_03.txt
  /tmp/peak_fixed_2025_12_04_05.txt
  /tmp/peak_fixed_2025_12_06_07.txt
  /tmp/peak_fixed_2025_12_08_09.txt
  /tmp/peak_fixed_2025_12_10_11.txt
  /tmp/peak_fixed_2025_12_12_13.txt
  /tmp/peak_fixed_2025_12_14_15.txt
  /tmp/peak_fixed_2025_12_15_to_19.txt
  /tmp/peak_fixed_2025_12_20.txt
  /tmp/peak_fixed_2025_12_21.txt
  /tmp/peak_fixed_2025_12_22.txt
  /tmp/peak_fixed_2025_12_23.txt
  /tmp/peak_fixed_2025_12_24.txt
  /tmp/peak_fixed_2025_12_25.txt
  /tmp/peak_fixed_2025_12_26.txt
  /tmp/peak_fixed_2025_12_27.txt
  /tmp/peak_fixed_2025_12_28.txt
  /tmp/peak_fixed_2025_12_29.txt
  /tmp/peak_fixed_2025_12_30.txt
  /tmp/peak_fixed_2025_12_31.txt
  /tmp/peak_fixed_2026_01_01.txt
  /tmp/peak_fixed_2026_01_02.txt
)

echo "📂 Ingesting ${#files[@]} files..."
echo ""

total_rows=0
for file in "${files[@]}"; do
  basename=$(basename "$file" .txt)
  echo "⏱️  $(date '+%H:%M:%S') - Processing: $basename..."
  python ingest_init_simple.py --input "$file" 2>&1 | grep -E "Parsed|Inserted"
  lines=$(tail -3 /tmp/insert_called.txt 2>/dev/null | grep "Inserted" | grep -oE "[0-9]+" | head -1)
  if [ -n "$lines" ]; then
    total_rows=$((total_rows + lines))
  fi
  echo ""
done

echo "====== INGEST COMPLETE ======"
echo "Total rows ingested: ~$total_rows"
echo ""
echo "📊 Final verification:"
python check_peak_detection.py 2>&1 | grep -E "Total rows|Celkem řádků|Hodnoty > 500" | head -5
