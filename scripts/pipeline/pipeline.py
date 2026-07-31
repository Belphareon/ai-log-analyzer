#!/usr/bin/env python3
"""
Incident Detection Pipeline
============================

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
from collections import Counter

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


class Pipeline:
    """
    Incident Detection Pipeline

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
        new_error_min_count: int = 50,

        # P93/CAP peak detection
        peak_detector = None,

        # Tráce-centric analýza (opt-in; backfill ji nechce kvůli výkonu)
        build_trace_patterns: bool = False,

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
            peak_detector=peak_detector,
        )
        self.phase_d = PhaseD_Score()
        self.phase_e = PhaseE_Classify()
        self.phase_f = PhaseF_Report()

        self.build_trace_patterns = build_trace_patterns

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

    @staticmethod
    def _populate_error_kind_facts(
        collection: IncidentCollection,
        fact_rows: Dict[tuple, List[Any]],
        fingerprint_metadata: Dict[str, Dict[str, str]],
        classifications: Dict[str, ClassificationResult],
    ) -> None:
        for (bucket, namespace, application, fingerprint), values in sorted(fact_rows.items()):
            count, first_seen, last_seen = values
            metadata = fingerprint_metadata[fingerprint]
            classification = classifications.get(fingerprint)
            collection.error_kind_facts.append({
                'window_start': bucket,
                'namespace': namespace,
                'application': application,
                'fingerprint': fingerprint,
                'error_type': metadata['error_type'],
                'category': classification.category.value if classification else 'unknown',
                'subcategory': classification.subcategory if classification else 'unclassified',
                'error_count': count,
                'first_event_at': first_seen,
                'last_event_at': last_seen,
                'sample_message': metadata['sample_message'],
                'metadata_quality': 'unknown',
            })
    
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
        print(f"🚀 PIPELINE - Run ID: {run_id}")
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
            pipeline_version="1.0",
            input_records=len(errors),
        )
        
        # Determine time range
        timestamps = [r.timestamp for r in records if r.timestamp]
        if timestamps:
            collection.time_range_start = min(timestamps)
            collection.time_range_end = max(timestamps)

        fact_rows = {}
        for record in records:
            if not record.timestamp:
                continue
            minute = (record.timestamp.minute // self.phase_b.window_minutes) * self.phase_b.window_minutes
            bucket = record.timestamp.replace(minute=minute, second=0, microsecond=0)
            key = (
                bucket,
                record.namespace or 'unknown',
                record.app_name or 'unknown',
                record.fingerprint,
            )
            fact = fact_rows.setdefault(key, [0, record.timestamp, record.timestamp])
            fact[0] += 1
            fact[1] = min(fact[1], record.timestamp)
            fact[2] = max(fact[2], record.timestamp)
        self._populate_error_kind_facts(
            collection,
            fact_rows,
            {
                fingerprint: {
                    'error_type': group_records[0].error_type,
                    'sample_message': group_records[0].raw_message[:500],
                }
                for fingerprint, group_records in groups.items()
            },
            classifications,
        )
        
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
                pipeline_version="1.0",
            )
            incident_seq += 1
            
            # From Phase A
            inc.normalized_message = group_records[0].normalized_message
            inc.error_type = group_records[0].error_type
            inc.raw_samples = [r.raw_message[:500] for r in group_records[:3]]

            app_counts = Counter(
                r.app_name for r in group_records
                if getattr(r, 'app_name', None)
            )
            namespace_counts = Counter(
                r.namespace for r in group_records
                if getattr(r, 'namespace', None)
            )
            trace_counts = Counter(
                r.trace_id for r in group_records
                if getattr(r, 'trace_id', None)
            )
            originator_counts = Counter(
                r.originator_application for r in group_records
                if getattr(r, 'originator_application', None)
            )

            # Collect unique values with deterministic ordering by contribution
            inc.apps = [name for name, _ in app_counts.most_common()]
            inc.namespaces = [name for name, _ in namespace_counts.most_common()]
            inc.versions = sorted({
                r.app_version for r in group_records
                if getattr(r, 'app_version', None) and r.app_version != 'unknown'
            })
            inc.trace_ids = [trace_id for trace_id, _ in trace_counts.most_common(10)]
            inc.originator_applications = [name for name, _ in originator_counts.most_common()]
            inc.app_event_counts = dict(app_counts)
            inc.namespace_event_counts = dict(namespace_counts)
            inc.trace_event_counts = dict(trace_counts)
            inc.originator_application_counts = dict(originator_counts)
            if hasattr(inc.trace_info, 'trace_ids'):
                inc.trace_info.trace_ids = inc.trace_ids.copy()
            
            # From Phase B
            inc.time.first_seen = measurement.first_seen
            inc.time.last_seen = measurement.last_seen
            inc.time.duration_sec = measurement.duration_sec
            
            inc.stats.baseline_rate = measurement.baseline_ewma
            inc.stats.baseline_median = measurement.baseline_median
            inc.stats.baseline_mad = measurement.baseline_mad
            inc.stats.current_rate = measurement.current_rate
            # Use total_count (sum across ALL windows) for DB storage
            # For regular phase (1 window): total_count == current_count
            # For backfill (96 windows): total_count = real total, current_count = last window only (often 0)
            inc.stats.current_count = measurement.total_count if measurement.total_count > 0 else measurement.current_count
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
        # TRACE PATTERNS (reálná trace-centric analýza z raw eventů, opt-in)
        # =====================================================================
        # Složí reálné časové osy z records (ne fabrikovaně) a seskupí trace se
        # stejným průběhem do patternů: occurrences = počet trace, total_errors,
        # avg/occ, errors-per-app, root cause + outcome. Non-blocking.
        collection.trace_patterns = []
        collection.trace_pattern_index = {}
        collection.trace_timelines = {}
        if self.build_trace_patterns:
            try:
                from analysis.trace_timeline import (
                    build_trace_timelines, group_traces_by_signature,
                )
                timelines = build_trace_timelines(records)
                patterns = group_traces_by_signature(timelines)
                index = {}
                for pat in patterns:
                    for tid in pat.trace_ids:
                        index[tid] = pat
                collection.trace_patterns = patterns
                collection.trace_pattern_index = index
                # Reálné per-trace timelines (pro trace-ownership dedup v reportu).
                collection.trace_timelines = timelines
                print(f"   ✅ Built {len(patterns)} trace patterns from {len(timelines)} traces")
            except Exception as e:
                print(f"   ⚠️ Trace pattern build failed (non-blocking): {e}")

        # =====================================================================
        # SAVE INTERMEDIATE
        # =====================================================================
        if save_intermediate and output_dir:
            intermediate_path = Path(output_dir) / f"intermediate_{run_id}.json"
            with open(intermediate_path, 'w') as f:
                json.dump(intermediate, f, indent=2, default=str)
            print(f"   💾 Saved intermediate: {intermediate_path}")
        
        return collection

    def run_streaming(
        self,
        aggregator,
        run_id: str = None,
        input_records: int = None,
    ) -> IncidentCollection:
        """
        Streaming varianta run() (r87).

        Konzumuje PŘEDPOČÍTANÉ agregáty ze `StreamingAggregator` místo držení všech
        recordů v RAM. Produkuje BIT-IDENTICKÉ výsledky jako run() nad stejnými logy
        (viz golden regression test) — reuse Phase B math helperů, Phase C detect(),
        Phase D/E a stejné incident-building logiky.
        """
        from datetime import timedelta

        agg = aggregator
        if not agg._finalized:
            agg.finalize()

        if run_id is None:
            run_id = f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        if input_records is None:
            input_records = agg.total_records

        print(f"\n{'='*80}")
        print(f"🚀 PIPELINE (streaming) - Run ID: {run_id}")
        print(f"{'='*80}")
        print(f"   Input: {input_records:,} errors | {agg.fingerprint_count} fingerprints")

        wm = self.phase_b.window_minutes
        cws = agg.current_window_start
        global_max_idx = agg.global_max_window_idx
        global_last_bucket = agg.global_last_bucket

        # =====================================================================
        # FÁZE B: Measure (replikace KROK 3 z phase_b_measure.py nad agregáty)
        # =====================================================================
        print(f"\n📊 PHASE B: Measure (streaming)")
        measurements: Dict[str, MeasurementResult] = {}
        for fp in agg.fp_order:
            acc = agg.acc[fp]
            window_counts = acc.window_counts
            if not window_counts or cws is None:
                continue  # bez timestampovaného recordu → žádný measurement (== Phase B)

            rates = []
            for i in range(global_max_idx + 1):
                b = cws + timedelta(minutes=i * wm)
                rates.append(window_counts.get(b, 0))

            current_rate = rates[-1] if rates else 0
            current_count = window_counts.get(global_last_bucket, 0)

            current_window_historical = rates[:-1] if len(rates) > 1 else []
            historical_rates = current_window_historical
            if fp in self.phase_b.historical_baseline:
                historical_rates = self.phase_b.historical_baseline[fp] + historical_rates
            elif self.phase_b.error_type_baseline:
                et = acc.error_type
                if et and et in self.phase_b.error_type_baseline:
                    historical_rates = self.phase_b.error_type_baseline[et] + historical_rates

            if historical_rates:
                ewma_rate = self.phase_b._calculate_ewma(historical_rates)
                median_rate, mad = self.phase_b._calculate_mad(historical_rates)
                has_baseline = True
            else:
                ewma_rate = 0
                median_rate = 0
                mad = 0
                has_baseline = False

            if has_baseline and ewma_rate > 0:
                trend_ratio = current_rate / ewma_rate
            else:
                trend_ratio = 1.0

            if trend_ratio > 1.2:
                trend_direction = "increasing"
            elif trend_ratio < 0.8:
                trend_direction = "decreasing"
            else:
                trend_direction = "stable"

            first_seen = acc.first_seen
            last_seen = acc.last_seen
            duration_sec = int((last_seen - first_seen).total_seconds()) if first_seen and last_seen else 0

            total_count = sum(window_counts.values())
            active_windows = sum(1 for v in window_counts.values() if v > 0)

            namespaces = list(acc.ns_meas)
            apps = list(acc.apps_meas)

            measurements[fp] = MeasurementResult(
                fingerprint=fp,
                current_count=current_count,
                current_rate=current_rate,
                baseline_ewma=ewma_rate if has_baseline else 0,
                baseline_mad=mad if has_baseline else 0,
                baseline_median=median_rate if has_baseline else 0,
                trend_ratio=trend_ratio,
                trend_direction=trend_direction,
                total_count=total_count,
                active_windows=active_windows,
                namespaces=namespaces,
                namespace_count=len(namespaces),
                apps=apps,
                app_count=len(apps),
                first_seen=first_seen,
                last_seen=last_seen,
                duration_sec=duration_sec,
            )
        print(f"   ✅ Measured {len(measurements)} fingerprints")

        # =====================================================================
        # FÁZE C: Detect (P93/CAP + reuse detect() + inkrementální burst)
        # =====================================================================
        print(f"\n🔍 PHASE C: Detect (streaming)")

        self.phase_c.prepare_namespace_peak_results({
            fingerprint: agg.acc[fingerprint].ns_bucket_counts
            for fingerprint in measurements
        })

        # --- Per-fingerprint detekce (reuse detect(); burst inkrementálně) ---
        detections: Dict[str, DetectionResult] = {}
        bt = self.phase_c.burst_threshold
        bwin_sec = self.phase_c.burst_window_sec
        for fp in measurements.keys():
            acc = agg.acc[fp]
            measurement = measurements[fp]
            result = self.phase_c.detect(
                measurement,
                fp_records=None,
                current_version=self.phase_c.latest_version(acc.versions),
                apps=list(acc.apps_meas),
                error_type=acc.error_type,
                normalized_message=acc.normalized_message,
                namespaces=list(acc.ns_meas),
            )
            # Event timestamps (detect() je nenastaví bez fp_records)
            result.first_event_ts = acc.first_seen
            result.last_event_ts = acc.last_seen

            # Burst z inkrementálního stavu (identická matematika jako _detect_burst)
            if acc.burst_ts_events >= 2 and acc.burst_n > 0:
                max_count = acc.burst_max
                avg_count = acc.burst_sum / acc.burst_n
                ratio = max_count / avg_count if avg_count > 0 else 0
                if ratio > bt:
                    result.flags.is_burst = True
                    result.add_evidence(
                        rule="burst",
                        current=float(max_count),
                        threshold=bt,
                        message=f"max/avg ratio ({ratio:.2f}) > {bt} "
                                f"({max_count} events in {bwin_sec}s window, avg {avg_count:.1f})",
                    )
            detections[fp] = result

        flag_counts = {
            'new': sum(1 for d in detections.values() if d.flags.is_new),
            'spike': sum(1 for d in detections.values() if d.flags.is_spike),
            'burst': sum(1 for d in detections.values() if d.flags.is_burst),
            'cross_ns': sum(1 for d in detections.values() if d.flags.is_cross_namespace),
        }
        print(f"   ✅ Detected flags: new={flag_counts['new']}, spike={flag_counts['spike']}, burst={flag_counts['burst']}, cross_ns={flag_counts['cross_ns']}")

        # =====================================================================
        # FÁZE D: Score
        # =====================================================================
        print(f"\n📈 PHASE D: Score (streaming)")
        scores = self.phase_d.score_batch(detections, measurements)

        # =====================================================================
        # FÁZE E: Classify
        # =====================================================================
        print(f"\n🏷️  PHASE E: Classify (streaming)")
        classify_input = [
            (fp, agg.acc[fp].normalized_message, agg.acc[fp].error_type)
            for fp in measurements.keys()
        ]
        classifications = self.phase_e.classify_batch(classify_input)

        # =====================================================================
        # BUILD INCIDENTS (mirror run())
        # =====================================================================
        print(f"\n🔨 Building Incident Objects (streaming)")
        collection = IncidentCollection(
            run_id=run_id,
            run_timestamp=datetime.utcnow(),
            pipeline_version="1.0",
            input_records=input_records,
        )
        if agg.min_ts is not None:
            collection.time_range_start = agg.min_ts
            collection.time_range_end = agg.max_ts

        self._populate_error_kind_facts(
            collection,
            agg.error_kind_facts,
            {
                fingerprint: {
                    'error_type': accumulator.error_type,
                    'sample_message': accumulator.raw_samples[0] if accumulator.raw_samples else '',
                }
                for fingerprint, accumulator in agg.acc.items()
            },
            classifications,
        )

        incident_seq = 1
        for fp in agg.fp_order:
            measurement = measurements.get(fp)
            detection = detections.get(fp)
            score_result = scores.get(fp)
            classification = classifications.get(fp)
            if not all([measurement, detection, score_result, classification]):
                continue

            acc = agg.acc[fp]
            inc = Incident(
                id=generate_incident_id(collection.run_timestamp, incident_seq),
                fingerprint=fp,
                pipeline_version="1.0",
            )
            incident_seq += 1

            inc.normalized_message = acc.normalized_message
            inc.error_type = acc.error_type
            inc.raw_samples = list(acc.raw_samples)

            app_counts = acc.app_counts
            namespace_counts = acc.ns_counts
            trace_counts = acc.trace_counts
            originator_counts = acc.originator_counts

            inc.apps = [name for name, _ in app_counts.most_common()]
            inc.namespaces = [name for name, _ in namespace_counts.most_common()]
            inc.versions = sorted(acc.versions)
            inc.trace_ids = [trace_id for trace_id, _ in trace_counts.most_common(10)]
            inc.originator_applications = [name for name, _ in originator_counts.most_common()]
            inc.app_event_counts = dict(app_counts)
            inc.namespace_event_counts = dict(namespace_counts)
            inc.trace_event_counts = dict(trace_counts)
            inc.originator_application_counts = dict(originator_counts)
            if hasattr(inc.trace_info, 'trace_ids'):
                inc.trace_info.trace_ids = inc.trace_ids.copy()

            inc.time.first_seen = measurement.first_seen
            inc.time.last_seen = measurement.last_seen
            inc.time.duration_sec = measurement.duration_sec

            inc.stats.baseline_rate = measurement.baseline_ewma
            inc.stats.baseline_median = measurement.baseline_median
            inc.stats.baseline_mad = measurement.baseline_mad
            inc.stats.current_rate = measurement.current_rate
            inc.stats.current_count = measurement.total_count if measurement.total_count > 0 else measurement.current_count
            inc.stats.namespaces = measurement.namespace_count
            inc.stats.trend_direction = measurement.trend_direction
            inc.stats.trend_ratio = measurement.trend_ratio

            inc.flags = detection.flags
            inc.evidence = detection.evidence

            inc.score = score_result.score
            inc.score_breakdown = score_result.breakdown
            inc.severity = IncidentSeverity(score_to_severity(score_result.score))

            inc.category = classification.category
            inc.subcategory = classification.subcategory

            collection.add_incident(inc)

        print(f"   ✅ Built {collection.total_incidents} incidents")

        # =====================================================================
        # TRACE PATTERNS (rekonstrukce z SQLite jen pro relevantní/top trace)
        # =====================================================================
        collection.trace_patterns = []
        collection.trace_pattern_index = {}
        collection.trace_timelines = {}
        if self.build_trace_patterns:
            try:
                from analysis.trace_timeline import (
                    build_trace_timelines, group_traces_by_signature,
                )
                records_iter = list(agg.iter_top_trace_records())
                timelines = build_trace_timelines(records_iter)
                patterns = group_traces_by_signature(timelines)
                index = {}
                for pat in patterns:
                    for tid in pat.trace_ids:
                        index[tid] = pat
                collection.trace_patterns = patterns
                collection.trace_pattern_index = index
                collection.trace_timelines = timelines
                print(f"   ✅ Built {len(patterns)} trace patterns from {len(timelines)} traces")
            except Exception as e:
                print(f"   ⚠️ Trace pattern build failed (non-blocking): {e}")

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
    parser = argparse.ArgumentParser(description='Incident Detection Pipeline')
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
    pipeline = Pipeline(
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
