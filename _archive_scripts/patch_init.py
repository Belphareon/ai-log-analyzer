# Patch script pro ingest_init_6windows.py
import re

with open('/home/jvsete/git/sas/ai-log-analyzer/scripts/ingest_init_6windows.py', 'r') as f:
    content = f.read()

# Change 1: Upravit range(1, 4) na range(1, 7) pro 6 oken
content = re.sub(
    r'for i in range\(1, 4\):  # -15min, -30min, -45min',
    'for i in range(1, 7):  # -15min, -30min, -45min, -60min, -75min, -90min',
    content
)

# Change 2: Odebrat logiku s historical days (refs_days)
# Nahradit blok s refs_days prázdným přiřazením
content = re.sub(
    r'# STEP 2: Get 3 previous days.*?refs_days\.append.*?\n',
    '# STEP 2 (INIT): No historical days - DB is empty\n    refs_days = []\n',
    content,
    flags=re.DOTALL
)

# Change 3: Upravit ratio decision - jen 35×
old_decision = r'''# STEP 5: Peak decision
    # Rule 1: Values < 10 are ALWAYS baseline \(never skip\)
    if mean_val < 10:
        is_peak = False
    # Rule 2: If reference < 10, use higher threshold \(50×\)
    elif reference < 10:
        is_peak = \(ratio >= 50\.0\)
    # Rule 3: Normal threshold \(15×\)
    else:
        is_peak = \(ratio >= 15\.0\)'''

new_decision = '''# STEP 5: Peak decision (INIT: simple 35× threshold)
    is_peak = (ratio >= 35.0)'''

content = re.sub(old_decision, new_decision, content)

with open('/home/jvsete/git/sas/ai-log-analyzer/scripts/ingest_init_6windows.py', 'w') as f:
    f.write(content)

print("✅ Patched successfully")
