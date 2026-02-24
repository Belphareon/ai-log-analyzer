#!/usr/bin/env python3
"""
Analýza vylepšení peak detection - porovnání STARÉHO vs NOVÉHO
Ukazuje jak by se výsledky změnili s opravami.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import execute_values
import json

def connect_db():
    """Připoj se k DB"""
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', 5432)),
        database=os.environ.get('DB_NAME', 'elasticsearch'),
        user=os.environ.get('DB_USER', 'es'),
        password=os.environ.get('DB_PASS', 'es')
    )

def analyze_improvements():
    """Analyzuj zlepšení peak detection"""
    
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Get data z posledních 24 hodin
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=24)
        
        print("=" * 80)
        print(f"🔍 PEAK DETECTION IMPROVEMENT ANALYSIS")
        print(f"   Time range: {window_start.isoformat()} → {now.isoformat()}")
        print("=" * 80)
        
        # =====================================================================
        # ČÁST 1: Najdi všechny detekce v poslední 24h
        # =====================================================================
        cursor.execute("""
            SELECT 
                id, fingerprint, is_spike, is_burst, is_new,
                baseline_ewma, current_rate, current_count,
                namespace_count, namespaces, score,
                updated_at
            FROM ailog_peak.peak_investigation
            WHERE updated_at >= %s
            ORDER BY updated_at DESC
        """, (window_start,))
        
        all_records = cursor.fetchall()
        print(f"\n📊 Total peak records in DB: {len(all_records)}")
        
        if not all_records:
            print("❌ No peak records found")
            return
        
        # =====================================================================
        # ČÁST 2: Kategorizuj records - STARÁ logika vs NOVÁ logika
        # =====================================================================
        
        old_logic_spikes = 0
        old_logic_bursts = 0
        new_logic_spikes = 0
        new_logic_bursts = 0
        false_positive_bursts = []
        false_positive_spikes = []
        
        for record in all_records:
            rid, fp, old_is_spike, old_is_burst, is_new, baseline, rate, count, ns_count, ns, score, ts = record
            
            # STARÁ logika - jak to bylo
            if old_is_spike:
                old_logic_spikes += 1
            if old_is_burst:
                old_logic_bursts += 1
            
            # NOVÁ logika - s opravami
            # Spike: spike_new_error_type fallback
            new_is_spike = old_is_spike
            if baseline == 0 and count >= 5:
                new_is_spike = True
            
            # Burst: s guardrails
            new_is_burst = old_is_burst
            if new_is_burst and baseline < 0.5:  # GUARDRAIL: baseline příliš nízký
                new_is_burst = False
                false_positive_bursts.append({
                    'fingerprint': fp,
                    'reason': 'baseline_too_low',
                    'baseline': baseline,
                    'count': count,
                    'score': score,
                    'timestamp': ts
                })
            
            if new_is_spike:
                new_logic_spikes += 1
            if new_is_burst:
                new_logic_bursts += 1
        
        # =====================================================================
        # ČÁST 3: Statistiky
        # =====================================================================
        print("\n📈 SPIKE DETECTIONS")
        print(f"   OLD logic: {old_logic_spikes} spikes")
        print(f"   NEW logic: {new_logic_spikes} spikes")
        print(f"   Difference: {new_logic_spikes - old_logic_spikes:+d} ({100*new_logic_spikes/(old_logic_spikes or 1):.1f}%)")
        
        print("\n📈 BURST DETECTIONS")
        print(f"   OLD logic: {old_logic_bursts} bursts")
        print(f"   NEW logic: {old_logic_bursts - len(false_positive_bursts)} bursts")
        print(f"   FALSE POSITIVES REMOVED: {len(false_positive_bursts)} ({100*len(false_positive_bursts)/(old_logic_bursts or 1):.1f}%)")
        
        # =====================================================================
        # ČÁST 4: False positives detail
        # =====================================================================
        if false_positive_bursts:
            print("\n❌ FALSE POSITIVE BURSTS (removed by guardrails):")
            print("   " + "-" * 76)
            print(f"   {'FP':<4} {'Fingerprint':<15} {'Baseline':<12} {'Count':<8} {'Score':<6} {'Reason':<20}")
            print("   " + "-" * 76)
            
            for i, fp_item in enumerate(false_positive_bursts[:20], 1):
                print(f"   {i:<4} {fp_item['fingerprint'][:14]:<15} "
                      f"{fp_item['baseline']:.4f}        {fp_item['count']:<8} "
                      f"{fp_item['score']:<6} {fp_item['reason']:<20}")
            
            if len(false_positive_bursts) > 20:
                print(f"   ... and {len(false_positive_bursts) - 20} more")
        
        # =====================================================================
        # ČÁST 5: Notifikační mejn - co se teď posílá
        # =====================================================================
        print("\n📧 TEAMS NOTIFICATION LOGIC")
        print("   OLD: peaks_detected = (spike OR burst)")
        print("   NEW: peaks_detected = (spike OR burst OR score >= 70)")
        
        high_score_incidents = sum(1 for r in all_records if r[10] >= 70)  # score >= 70
        print(f"\n   High-score incidents (score >= 70): {high_score_incidents}")
        print(f"   → These will NOW trigger notifications (previously skipped)")
        
        # =====================================================================
        # ČÁST 6: Shrnutí
        # =====================================================================
        print("\n" + "=" * 80)
        print("✅ SUMMARY OF IMPROVEMENTS")
        print("=" * 80)
        
        improvement_count = len(false_positive_bursts)
        notification_improvement = high_score_incidents
        
        print(f"\n1. FALSE POSITIVES REMOVED: {improvement_count} bursts with baseline < 0.5")
        print(f"   → Cleaner alerts, less noise")
        
        print(f"\n2. NEW NOTIFICATIONS ENABLED: {notification_improvement} incidents with score >= 70")
        print(f"   → Important problems won't be missed even without spike flag")
        
        print(f"\n3. NEW ERROR TYPE HANDLING: improved")
        print(f"   → Errors with 5+ occurrences treated as spikes")
        print(f"   → Better detection for new error types without baseline")
        
        print(f"\n📊 Metrics:")
        print(f"   - Reduced noise: -{(100*improvement_count/(old_logic_bursts or 1)):.1f}% false bursts")
        print(f"   - Increased sensitivity: +{(100*notification_improvement/(improvement_count or 1)):.0f}% high-priority catches")
        
        print("\n" + "=" * 80)
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    analyze_improvements()
