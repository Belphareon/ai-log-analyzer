import os,re,json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from collections import Counter

repo=Path('/home/jvsete/git/ai-log-analyzer')
os.chdir(repo)
sys.path.insert(0,str(repo/'scripts'))
sys.path.insert(0,str(repo))

from dotenv import load_dotenv
load_dotenv(repo/'.env')
load_dotenv(repo/'config/.env')

from scripts.core.fetch_unlimited import fetch_unlimited
from scripts.core.problem_registry import ProblemRegistry
from scripts.core.baseline_loader import BaselineLoader
from scripts.pipeline import PipelineV6
from scripts.pipeline.phase_a_parse import PhaseA_Parser
from scripts.analysis import aggregate_by_problem_key
from scripts.regular_phase_v6 import get_db_connection

window_minutes=1440
now=datetime.now(timezone.utc)
quarter=(now.minute//15)*15
window_end=now.replace(minute=quarter,second=0,microsecond=0)
window_start=window_end-timedelta(minutes=window_minutes)

print(f"window={window_start.isoformat()} -> {window_end.isoformat()}")

registry=ProblemRegistry(str(repo/'registry'))
registry.load()
print(f"known_fingerprints_registry={len(registry.get_all_known_fingerprints())}")

errors=fetch_unlimited(window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),window_end.strftime('%Y-%m-%dT%H:%M:%SZ'))
print(f"errors_fetched={len(errors)}")

historical_baseline={}
try:
    db_conn=get_db_connection()
    bl=BaselineLoader(db_conn)
    parser=PhaseA_Parser()
    sample_error_types=set()
    for e in errors[:1000]:
        et=parser.extract_error_type(e.get('message',''))
        if et and et!='Unknown':
            sample_error_types.add(et)
    if sample_error_types:
        historical_baseline=bl.load_historical_rates(error_types=list(sample_error_types),lookback_days=7,min_samples=3)
    db_conn.close()
except Exception as ex:
    print(f"baseline_load_warning={ex}")

pipeline=PipelineV6(
    spike_threshold=float(os.getenv('SPIKE_THRESHOLD',3.0)),
    ewma_alpha=float(os.getenv('EWMA_ALPHA',0.3)),
    window_minutes=window_minutes,
)
pipeline.phase_b.error_type_baseline=historical_baseline
pipeline.phase_c.registry=registry
pipeline.phase_c.known_fingerprints=registry.get_all_known_fingerprints().copy()

collection=pipeline.run(errors,run_id='audit-24h')
incs=collection.incidents
print(f"incidents={len(incs)}")

c=Counter()
fails=[]

for inc in incs:
    ev_rules=[e.rule for e in (inc.evidence or [])]

    if inc.flags.is_spike:
        c['spike_flag']+=1
        spike_ev=[e for e in inc.evidence if e.rule in ('spike_ewma','spike_mad','spike_new_error_type')]
        if not spike_ev:
            fails.append(('spike_no_evidence',inc.fingerprint))
            continue
        ok=False
        for e in spike_ev:
            if e.rule=='spike_ewma' and inc.stats.baseline_rate>0:
                ratio=(inc.stats.current_rate/inc.stats.baseline_rate) if inc.stats.baseline_rate else 0
                if ratio>float(e.threshold):
                    ok=True
            elif e.rule=='spike_mad' and e.threshold is not None:
                if inc.stats.current_rate>float(e.threshold):
                    ok=True
            elif e.rule=='spike_new_error_type':
                if inc.stats.baseline_rate==0 and inc.stats.current_count>=5:
                    ok=True
        if ok:
            c['spike_rule_ok']+=1
        else:
            fails.append(('spike_rule_mismatch',inc.fingerprint,[(e.rule,e.threshold,e.message) for e in spike_ev],inc.stats.current_rate,inc.stats.baseline_rate,inc.stats.current_count))

    if inc.flags.is_burst:
        c['burst_flag']+=1
        burst_ev=[e for e in inc.evidence if e.rule=='burst']
        if not burst_ev:
            fails.append(('burst_no_evidence',inc.fingerprint))
        else:
            m=burst_ev[0].message or ''
            mm=re.search(r'ratio \(([-0-9.]+)\) > ([-0-9.]+)',m)
            if mm and float(mm.group(1))>float(mm.group(2)):
                c['burst_rule_ok']+=1
            else:
                fails.append(('burst_rule_unverifiable_or_fail',inc.fingerprint,m,burst_ev[0].threshold))

    if inc.flags.is_new:
        c['new_flag']+=1
        if 'new_fingerprint' in ev_rules:
            c['new_rule_ok']+=1
        else:
            fails.append(('new_no_new_fingerprint_evidence',inc.fingerprint,ev_rules))

problems=aggregate_by_problem_key(incs)
predicted=set()
for p in problems.values():
    if p.has_spike:
        predicted.add(f"PEAK:{p.category}:{p.flow}:spike")
    if p.has_burst:
        predicted.add(f"PEAK:{p.category}:{p.flow}:burst")

peaks_path=repo/'ai-data'/'latest'/'peaks_table.json'
obj=json.loads(peaks_path.read_text(encoding='utf-8'))
rows=obj.get('peaks',[])
recent=[]
for r in rows:
    ls=datetime.strptime(r['last_seen'],'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
    if ls>=window_start:
        recent.append(r)
exported={r['problem_key'].lower() for r in recent}
predicted_l={k.lower() for k in predicted}
missing=sorted(predicted_l-exported)
extra=sorted(exported-predicted_l)

print('---AUDIT_SUMMARY---')
print(f"spike_flags={c['spike_flag']} spike_rule_ok={c['spike_rule_ok']}")
print(f"burst_flags={c['burst_flag']} burst_rule_ok={c['burst_rule_ok']}")
print(f"new_flags={c['new_flag']} new_rule_ok={c['new_rule_ok']}")
print(f"predicted_peak_keys={len(predicted_l)} exported_recent_peak_keys={len(exported)}")
print(f"missing_in_export={len(missing)} extra_in_export={len(extra)}")
if missing:
    print('missing_sample=',missing[:10])
if extra:
    print('extra_sample=',extra[:10])
print(f"validation_failures={len(fails)}")
if fails:
    print('fail_sample=',fails[:5])
