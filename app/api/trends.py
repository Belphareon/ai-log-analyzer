"""Trends API - Weekly error analysis with large dataset support"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, timedelta
from typing import List

from app.services.trend_analyzer import trend_analyzer
from app.services.pattern_detector import pattern_detector
from app.schemas.trends import WeeklyTrendsResponse, ErrorPattern, KnownIssue, PeakEvent


def calculate_namespace_breakdown(error_list, total_errors, sample_size):
    """Calculate namespace distribution with extrapolation"""
    namespaces = {}
    for e in error_list:
        ns = e.get('namespace', 'unknown')
        namespaces[ns] = namespaces.get(ns, 0) + 1
    
    # Extrapolate to total
    ns_extrapolated = {}
    for ns, count in namespaces.items():
        ns_extrapolated[ns] = int((count / sample_size) * total_errors) if sample_size > 0 else count
    
    return ns_extrapolated

router = APIRouter(prefix="/trends", tags=["trends"])

@router.get("/weekly", response_model=WeeklyTrendsResponse)
async def get_weekly_trends(
    days: int = Query(default=7, ge=1, le=30, description="Počet dní k analýze"),
    max_sample: int = Query(default=50000, ge=1000, le=100000, description="Max vzorek errorů")
):
    """
    Weekly error trends with ML pattern detection
    
    Uses ES scroll API for large datasets (up to 100k errors)
    
    Returns:
    - Opakující se problémy
    - Nové problémy  
    - Známé issues k fixnutí
    - Coverage statistiky
    """
    # Time range
    time_to = datetime.utcnow()
    time_from = time_to - timedelta(days=days)
    
    # Fetch errors using scroll API
    errors, total = await trend_analyzer.fetch_errors_batch(
        time_from=time_from,
        time_to=time_to,
        batch_size=10000,
        max_total=max_sample
    )
    
    coverage = trend_analyzer.calculate_coverage(len(errors), total)
    
    # Cluster by pattern
    clusters = pattern_detector.cluster_errors(errors)
    
    # Build patterns
    recurring = []
    new_issues = []
    known = []
    
    for normalized, error_list in clusters.items():
        if len(error_list) < 3:
            continue
            
        first_ts = min(e['timestamp'] for e in error_list)
        last_ts = max(e['timestamp'] for e in error_list)
        apps = list(set(e['app'] for e in error_list))
        
        error_code = pattern_detector.extract_error_code(error_list[0]['message'])
        
        # Extrapolate count to total
        sample_count = len(error_list)
        extrapolated_count = int((sample_count / len(errors)) * total) if len(errors) > 0 else sample_count
        
        ns_breakdown = calculate_namespace_breakdown(error_list, total, len(errors))
        
        pattern = ErrorPattern(
            fingerprint=normalized[:50],
            error_code=error_code,
            message_sample=error_list[0]['message'][:150],
            count=extrapolated_count,  # Extrapolated!
            first_seen=first_ts,
            last_seen=last_ts,
            affected_apps=apps[:5],
            affected_namespaces=ns_breakdown,
            status="recurring" if (last_ts - first_ts).days > 1 else "new"
        )
        
        if pattern.status == "recurring":
            recurring.append(pattern)
            
            # Add to known issues if serious
            if sample_count > 10:
                card_id = pattern_detector.extract_card_id(error_list[0]['message'])
                
                occurrences_today = len([e for e in error_list if (time_to - e['timestamp']).days < 1])
                extrapolated_today = int((occurrences_today / len(errors)) * total) if len(errors) > 0 else occurrences_today
                
                known.append(KnownIssue(
                    fingerprint=normalized[:50],
                    error_code=error_code,
                    description=f"Recurring: {normalized[:100]}",
                    occurrences_total=extrapolated_count,
                    occurrences_today=extrapolated_today,
                    first_seen=first_ts,
                    last_seen=last_ts,
                    affected_apps=apps[:5],
                    affected_namespaces=ns_breakdown,
                    sample_trace_id=error_list[0].get('trace_id'),
                    sample_timestamp=error_list[0]['timestamp'],
                    recommendation=f"Investigate {error_code or 'error'}" + (f" for Card ID {card_id}" if card_id else ""),
                    priority="critical" if extrapolated_count > 10000 else "high" if extrapolated_count > 1000 else "medium"
                ))
        else:
            new_issues.append(pattern)
            
            # Also add significant new issues to known list
            if sample_count > 20:
                card_id = pattern_detector.extract_card_id(error_list[0]['message'])
                
                known.append(KnownIssue(
                    fingerprint=normalized[:50],
                    error_code=error_code,
                    description=f"New issue: {normalized[:100]}",
                    occurrences_total=extrapolated_count,
                    occurrences_today=extrapolated_count,
                    first_seen=first_ts,
                    last_seen=last_ts,
                    affected_apps=apps[:5],
                    affected_namespaces=ns_breakdown,
                    sample_trace_id=error_list[0].get('trace_id'),
                    sample_timestamp=error_list[0]['timestamp'],
                    recommendation=f"Monitor {error_code or 'new error'}" + (f" for Card ID {card_id}" if card_id else ""),
                    priority="high" if extrapolated_count > 5000 else "medium"
                ))
    
    # Sort by extrapolated count
    recurring.sort(key=lambda x: x.count, reverse=True)
    new_issues.sort(key=lambda x: x.count, reverse=True)
    known.sort(key=lambda x: x.occurrences_total, reverse=True)
    
    # Recommendations
    recommendations = []
    recommendations.append(f"Analyzed {len(errors):,} errors ({coverage:.1f}% coverage) from {total:,} total")
    
    if known:
        top = known[0]
        recommendations.append(f"FIX PRIORITY: {top.error_code or 'Top issue'} - ~{top.occurrences_total:,} occurrences ({top.priority})")
    
    if len(recurring) > 5:
        total_recurring = sum(p.count for p in recurring[:10])
        recommendations.append(f"Review {len(recurring)} recurring patterns (~{total_recurring:,} errors)")
    
    if len(new_issues) > 0:
        total_new = sum(p.count for p in new_issues[:10])
        recommendations.append(f"Monitor {len(new_issues)} new patterns (~{total_new:,} errors)")
    
    return WeeklyTrendsResponse(
        period_start=time_from,
        period_end=time_to,
        total_errors=total,
        sample_size=len(errors),
        coverage_percent=coverage,
        recurring_issues=recurring[:20],  # Více pro weekly/daily
        new_issues=new_issues[:20],
        known_issues=known[:30],  # Více known issues
        peaks=[],
        recommendations=recommendations
    )
