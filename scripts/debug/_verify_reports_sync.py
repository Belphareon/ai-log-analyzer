from pathlib import Path
import hashlib
import re

clear_path = Path('/home/jvsete/git/ai-log-analyzer/ai-data/peaks_24h_clear_table.md')
main_path = Path('/home/jvsete/git/ai-log-analyzer/ai-data/active_peaks_24h_investigation.md')

clear_txt = clear_path.read_text(encoding='utf-8')
main_txt = main_path.read_text(encoding='utf-8')

h_clear = hashlib.sha256(clear_txt.encode('utf-8')).hexdigest()
h_main = hashlib.sha256(main_txt.encode('utf-8')).hexdigest()

m1 = re.search(r'db_buckets_over_threshold: (\d+)', clear_txt)
m2 = re.search(r'db_missed_candidates: (\d+)', clear_txt)

print(f'same={h_clear == h_main}')
print(f'sha_clear={h_clear}')
print(f'sha_main={h_main}')
print(f"db_buckets_over_threshold={m1.group(1) if m1 else 'n/a'}")
print(f"db_missed_candidates={m2.group(1) if m2 else 'n/a'}")
