#!/usr/bin/env python3
"""
Pipeline V6 - Incident Detection Pipeline
==========================================

Striktně oddělené fáze:
A: Parse & Normalize
B: Measure (EWMA, MAD)
C: Detect (boolean flags)
D: Score (váhová funkce)
E: Classify (taxonomy)
F: Report (render)

Podporuje:
- Uložení mezi-výstupů po každé fázi
- Replay z snapshotu
- Regression testing

Použití:
    # Normální běh
    python pipeline.py data/batches/2026-01-20/
    
    # S uložením snapshotu
    python pipeline.py data/batches/2026-01-20/ --save-snapshot /tmp/snapshots/
    
    # Replay a porovnání
    python pipeline.py data/batches/2026-01-20/ --replay /tmp/snapshots/summary_20260120.json
"""

import json
import sys
import os
import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict

# Add scripts/pipeline to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from incident import (
    Incident, IncidentCollection, IncidentCategory, IncidentSeverity,
    TimeInfo, Stats, Flags, ScoreBreakdown, Evidence,
    generate_incident_id, generate_fingerprint
)
from phase_a_parse import PhaseA_Parser, NormalizedRecord, group_by_fingerprint
from phase_b_measure import PhaseB_Measure, MeasurementResult
from phase_c_detect import PhaseC_Detect, DetectionResult
from phase_d_score import PhaseD_Score, ScoreResult, score_to_severity
from phase_e_classify import PhaseE_Classify, ClassificationResult
from phase_f_report import PhaseF_Report


class PipelineV6:
    """
    Incident Detection Pipeline V6
    
    Orchestruje 6 fází:
    A → B → C → D → E → F
    
    Každá fáze jen přidává data, nic neodstraňuje.
    """
    
    def __init__(
        self,
        # Phase B config
        window_minutes: int = 15,
        ewma_alpha: float = 0.3,
        baseline_windows: int = 20,
        
        # Phase C config
        spike_threshold: float = 3.0,
        spike_mad_threshold: float = 3.0,
        cross_ns_threshold: int = 2,
        
        # Database connection (optional)
        db_conn = None,
    ):
        # Initialize phases
        self.phase_a = PhaseA_Parser()
        self.phase_b = PhaseB_Measure(
            window_minutes=window_minutes,
            ewma_alpha=ewma_alpha,
            baseline_windows=baseline_windows,
        )
        self.phase_c = PhaseC_Detect(
            spike_threshold=spike_threshold,
            spike_mad_threshold=spike_mad_threshold,
            cross_ns_threshold=cross_ns_threshold,
        )
        self.phase_d = PhaseD_Score()
        self.phase_e = PhaseE_Classify()
        self.phase_f = PhaseF_Report()
        
        self.db_conn = db_conn
        
        # Load known data from DB
        if db_conn:
            self._load_known_data()
    
    def _load_known_data(self):
        """Load known fingerprints and fixes from DB"""
        try:
            self.phase_c.load_known_from_db(self.db_conn)
            print(f"✅ Loaded {len(self.phase_c.known_fingerprints)} known fingerprints")
            print(f"✅ Loaded {len(self.phase_c.known_fixes)} known fixes")
        except Exception as e:
            print(f"⚠️  Could not load known data: {e}")
    
    def run(
        self,
        errors: List[dict],
        run_id: str = None,
        save_intermediate: bool = False,
        output_dir: str = None,
    ) -> IncidentCollection:
        """
        Spustí kompletní pipeline.
        
        Vstup: List raw error dicts
        Výstup: IncidentCollection
        """
        if run_id is None:
            run_id = f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        
        print(f"\n{'='*80}")
        print(f"🚀 PIPELINE V4 - Run ID: {run_id}")
        print(f"{'='*80}")
        print(f"   Input: {len(errors):,} errors")
        
        intermediate = {}
        
        # =====================================================================
        # FÁZE A: Parse & Normalize
        # =====================================================================
        print(f"\n📋 PHASE A: Parse & Normalize")
        
        records = self.phase_a.parse_batch(errors)
        groups = group_by_fingerprint(records)
        
        print(f"   ✅ Parsed {len(records):,} records")
        print(f"   ✅ Found {len(groups)} unique fingerprints")
        
        if save_intermediate:
            intermediate['phase_a'] = {
                'record_count': len(records),
                'fingerprint_count': len(groups),
                'fingerprints': list(groups.keys()),
            }
        
        # =====================================================================
        # FÁZE B: Measure
        # =====================================================================
        print(f"\n📊 PHASE B: Measure")
        
        measurements = self.phase_b.measure(records)
        
        print(f"   ✅ Measured {len(measurements)} fingerprints")
        
        if save_intermediate:
            intermediate['phase_b'] = {
                fp: {
                    'current_rate': m.current_rate,
                    'baseline_ewma': m.baseline_ewma,
                    'baseline_mad': m.baseline_mad,
                    'trend_ratio': m.trend_ratio,
                }
                for fp, m in measurements.items()
            }
        
        # =====================================================================
        # FÁZE C: Detect
        # =====================================================================
        print(f"\n🔍 PHASE C: Detect")
        
        detections = self.phase_c.detect_batch(measurements, records)
        
        # Count flags
        flag_counts = {
            'new': sum(1 for d in detections.values() if d.flags.is_new),
            'spike': sum(1 for d in detections.values() if d.flags.is_spike),
            'burst': sum(1 for d in detections.values() if d.flags.is_burst),
            'cross_ns': sum(1 for d in detections.values() if d.flags.is_cross_namespace),
        }
        
        print(f"   ✅ Detected flags: new={flag_counts['new']}, spike={flag_counts['spike']}, burst={flag_counts['burst']}, cross_ns={flag_counts['cross_ns']}")
        
        if save_intermediate:
            intermediate['phase_c'] = {
                'flag_counts': flag_counts,
                'detections': {
                    fp: {
                        'is_new': d.flags.is_new,
                        'is_spike': d.flags.is_spike,
                        'is_burst': d.flags.is_burst,
                        'is_cross_namespace': d.flags.is_cross_namespace,
                        'evidence_count': len(d.evidence),
                    }
                    for fp, d in detections.items()
                }
            }
        
        # =====================================================================
        # FÁZE D: Score
        # =====================================================================
        print(f"\n📈 PHASE D: Score")
        
        scores = self.phase_d.score_batch(detections, measurements)
        
        # Score distribution
        score_dist = {
            'critical': sum(1 for s in scores.values() if s.score >= 80),
            'high': sum(1 for s in scores.values() if 60 <= s.score < 80),
            'medium': sum(1 for s in scores.values() if 40 <= s.score < 60),
            'low': sum(1 for s in scores.values() if 20 <= s.score < 40),
            'info': sum(1 for s in scores.values() if s.score < 20),
        }
        
        print(f"   ✅ Score distribution: {score_dist}")
        
        if save_intermediate:
            intermediate['phase_d'] = {
                'score_distribution': score_dist,
                'scores': {fp: s.score for fp, s in scores.items()},
            }
        
        # =====================================================================
        # FÁZE E: Classify
        # =====================================================================
        print(f"\n🏷️  PHASE E: Classify")
        
        # Prepare classification input
        classify_input = [
            (fp, groups[fp][0].normalized_message, groups[fp][0].error_type)
            for fp in groups.keys()
        ]
        
        classifications = self.phase_e.classify_batch(classify_input)
        
        # Category distribution
        cat_dist = {}
        for c in classifications.values():
            cat = c.category.value
            cat_dist[cat] = cat_dist.get(cat, 0) + 1
        
        print(f"   ✅ Category distribution: {cat_dist}")
        
        if save_intermediate:
            intermediate['phase_e'] = {
                'category_distribution': cat_dist,
            }
        
        # =====================================================================
        # BUILD INCIDENTS
        # =====================================================================
        print(f"\n🔨 Building Incident Objects")
        
        collection = IncidentCollection(
            run_id=run_id,
            run_timestamp=datetime.utcnow(),
            pipeline_version="4.0",
            input_records=len(errors),
        )
        
        # Determine time range
        timestamps = [r.timestamp for r in records if r.timestamp]
        if timestamps:
            collection.time_range_start = min(timestamps)
            collection.time_range_end = max(timestamps)
        
        # Build incidents
        incident_seq = 1
        
        for fp, group_records in groups.items():
            measurement = measurements.get(fp)
            detection = detections.get(fp)
            score_result = scores.get(fp)
            classification = classifications.get(fp)
            
            if not all([measurement, detection, score_result, classification]):
                continue
            
            # Create incident
            inc = Incident(
                id=generate_incident_id(collection.run_timestamp, incident_seq),
                fingerprint=fp,
                pipeline_version="4.0",
            )
            incident_seq += 1
            
            # From Phase A
            inc.normalized_message = group_records[0].normalized_message
            inc.error_type = group_records[0].error_type
            inc.raw_samples = [r.raw_message[:500] for r in group_records[:3]]
            
            # Collect unique values
            inc.apps = list(set(r.app_name for r in group_records))
            inc.namespaces = list(set(r.namespace for r in group_records))
            inc.versions = list(set(r.app_version for r in group_records if r.app_version != 'unknown'))
            inc.trace_ids = list(set(r.trace_id for r in group_records if r.trace_id))[:10]
            
            # From Phase B
            inc.time.first_seen = measurement.first_seen
            inc.time.last_seen = measurement.last_seen
            inc.time.duration_sec = measurement.duration_sec
            
            inc.stats.baseline_rate = measurement.baseline_ewma
            inc.stats.baseline_mad = measurement.baseline_mad
            inc.stats.current_rate = measurement.current_rate
            inc.stats.current_count = measurement.current_count
            inc.stats.namespaces = measurement.namespace_count
            inc.stats.trend_direction = measurement.trend_direction
            inc.stats.trend_ratio = measurement.trend_ratio
            
            # From Phase C
            inc.flags = detection.flags
            inc.evidence = detection.evidence
            
            # From Phase D
            inc.score = score_result.score
            inc.score_breakdown = score_result.breakdown
            inc.severity = IncidentSeverity(score_to_severity(score_result.score))
            
            # From Phase E
            inc.category = classification.category
            inc.subcategory = classification.subcategory
            
            collection.add_incident(inc)
        
        print(f"   ✅ Built {collection.total_incidents} incidents")
        
        # =====================================================================
        # SAVE INTERMEDIATE
        # =====================================================================
        if save_intermediate and output_dir:
            intermediate_path = Path(output_dir) / f"intermediate_{run_id}.json"
            with open(intermediate_path, 'w') as f:
                json.dump(intermediate, f, indent=2, default=str)
            print(f"   💾 Saved intermediate: {intermediate_path}")
        
        return collection
    
    def replay_and_compare(
        self,
        errors: List[dict],
        snapshot_path: str,
    ) -> Dict[str, Any]:
        """
        Spustí pipeline a porovná s předchozím snapshotem.
        
        Pro regression testing.
        """
        print(f"\n🔄 REPLAY MODE - Comparing with {snapshot_path}")
        
        # Load previous snapshot
        with open(snapshot_path) as f:
            previous = json.load(f)
        
        # Run current
        current_collection = self.run(errors)
        
        # Compare
        comparison = {
            'previous_run_id': previous.get('run_id'),
            'current_run_id': current_collection.run_id,
            
            'incident_count': {
                'previous': previous.get('total_incidents', 0),
                'current': current_collection.total_incidents,
                'diff': current_collection.total_incidents - previous.get('total_incidents', 0),
            },
            
            'severity_changes': {},
            'score_changes': {},
        }
        
        # Compare severity distribution
        prev_severity = previous.get('by_severity', {})
        curr_severity = current_collection.by_severity
        
        for sev in ['critical', 'high', 'medium', 'low', 'info']:
            prev = prev_severity.get(sev, 0)
            curr = curr_severity.get(sev, 0)
            if prev != curr:
                comparison['severity_changes'][sev] = {
                    'previous': prev,
                    'current': curr,
                    'diff': curr - prev,
                }
        
        # Print comparison
        print(f"\n📊 COMPARISON RESULTS")
        print(f"   Incidents: {comparison['incident_count']['previous']} → {comparison['incident_count']['current']} ({comparison['incident_count']['diff']:+d})")
        
        if comparison['severity_changes']:
            print(f"   Severity changes:")
            for sev, change in comparison['severity_changes'].items():
                print(f"      {sev}: {change['previous']} → {change['current']} ({change['diff']:+d})")
        else:
            print(f"   ✅ No severity changes")
        
        return comparison


# ============================================================================
# DATA LOADING
# ============================================================================

def load_batch_files(batch_dir: str) -> List[dict]:
    """Load error batches from directory"""
    all_errors = []
    batch_path = Path(batch_dir)
    
    for batch_file in sorted(batch_path.glob("batch_*.json")):
        if "summary" in str(batch_file):
            continue
        
        with open(batch_file) as f:
            data = json.load(f)
            errors = data if isinstance(data, list) else data.get('errors', [])
            all_errors.extend(errors)
            print(f"   ✓ {batch_file.name}: {len(errors):,} errors")
    
    return all_errors


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Pipeline V4 - Incident Detection')
    parser.add_argument('input', help='Input directory with batch JSON files')
    parser.add_argument('--save-snapshot', type=str, help='Save snapshot to directory')
    parser.add_argument('--save-intermediate', action='store_true', help='Save intermediate phase outputs')
    parser.add_argument('--replay', type=str, help='Compare with previous snapshot')
    parser.add_argument('--output-json', type=str, help='Output JSON file')
    parser.add_argument('--output-md', type=str, help='Output Markdown file')
    parser.add_argument('--quiet', action='store_true', help='Suppress console output')
    
    # Phase config
    parser.add_argument('--spike-threshold', type=float, default=3.0)
    parser.add_argument('--ewma-alpha', type=float, default=0.3)
    
    args = parser.parse_args()
    
    # Load data
    print(f"\n📂 Loading data from {args.input}")
    errors = load_batch_files(args.input)
    
    if not errors:
        print("❌ No errors loaded")
        return 1
    
    print(f"\n✅ Loaded {len(errors):,} total errors")
    
    # Create pipeline
    pipeline = PipelineV6(
        spike_threshold=args.spike_threshold,
        ewma_alpha=args.ewma_alpha,
    )
    
    # Run
    if args.replay:
        comparison = pipeline.replay_and_compare(errors, args.replay)
        return 0
    
    collection = pipeline.run(
        errors,
        save_intermediate=args.save_intermediate,
        output_dir=args.save_snapshot,
    )
    
    # Report
    reporter = PhaseF_Report()
    
    if not args.quiet:
        print(f"\n{'='*80}")
        print("📝 PHASE F: Report")
        print(f"{'='*80}")
        reporter.print_console(collection)
    
    # Save outputs
    if args.output_json:
        reporter.save_json(collection, args.output_json)
        print(f"\n💾 Saved JSON: {args.output_json}")
    
    if args.output_md:
        reporter.save_markdown(collection, args.output_md)
        print(f"💾 Saved Markdown: {args.output_md}")
    
    if args.save_snapshot:
        files = reporter.save_snapshot(collection, args.save_snapshot)
        print(f"\n💾 Saved snapshot:")
        for name, path in files.items():
            print(f"   {name}: {path}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
