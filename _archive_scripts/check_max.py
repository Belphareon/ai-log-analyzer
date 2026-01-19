import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT',5432)), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()

print("="*70)
print("HIGHEST VALUE DETAILS")
print("="*70)
cur.execute("""
    SELECT namespace, day_of_week, hour_of_day, quarter_hour, mean_errors, samples_count
    FROM ailog_peak.peak_statistics 
    ORDER BY mean_errors DESC 
    LIMIT 1
""")
ns, day, hr, qtr, val, samples = cur.fetchone()
days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
print(f"Value: {val:.1f}")
print(f"Time: {days[day]} {hr:02d}:{qtr*15:02d}")
print(f"Namespace: {ns}")
print(f"Samples (days aggregated): {samples}")

print("\n" + "="*70)
print("CHECK: Was a peak skipped at Mon 15:30 pcb-dev?")
print("="*70)
import subprocess
result = subprocess.run("grep 'day=0.*15:30.*pcb-dev-01-app' /tmp/peaks_skipped.log", shell=True, capture_output=True, text=True)
if result.stdout:
    print("YES - Found skipped peak(s):")
    print(result.stdout)
    print("\n💡 CONCLUSION: Peak WAS detected and skipped, but 41,635 in DB")
    print("   is likely AGGREGATED from multiple days (samples={})".format(samples))
else:
    print("NO - No peak skipped at this time/namespace")
    print("\n💡 CONCLUSION: This value is LEGITIMATE (not a peak)")

conn.close()
