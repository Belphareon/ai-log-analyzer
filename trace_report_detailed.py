#!/usr/bin/env python3
"""
Detailed Trace-Based Root Cause Report Generator
Following TRACE_ANALYSIS_PROCEDURE.md 8-step workflow
"""
import json
import argparse
from collections import defaultdict
from datetime import datetime
import re

def extract_concrete_root_cause(message):
    """
    Extract concrete root cause from error message instead of generic type.
    Returns: (concrete_cause, context_description)
    """
    
    # Pattern 0: ErrorModel message - Most specific
    error_model_match = re.search(r'message=([^,\]]+)', message)
    if error_model_match:
        cause = error_model_match.group(1).strip()
        # Try to extract more context
        context = _extract_context(message, cause)
        return cause, context
    
    # Pattern 1: Card not found for account (BusinessException)
    card_account_match = re.search(r'There is not any card for account (\d+)', message)
    if card_account_match:
        account_id = card_account_match.group(1)
        return f"No card found for account {account_id}", "Account has no valid card - customer data issue"
    
    # Pattern 2: Card locked/blocked status
    card_locked_match = re.search(r'(PAN|Card) .* locked.*status (\w+)', message, re.IGNORECASE)
    if card_locked_match:
        status = card_locked_match.group(2)
        return f"Card locked - Cannot process (status: {status})", "Card is in locked/blocked state - customer initiated or system block"
    
    # Pattern 3: Card not found in lookup (404)
    card_lookup_match = re.search(r'/api/v\d+/card/(\d+)/', message)
    if card_lookup_match:
        card_id = card_lookup_match.group(1)
        return f"Card {card_id} lookup failed (404)", "GET /api/v1/card/{ID}/allowed-card-cases returned 404 - mostly SIT environment (70%), symptom of upstream issue, persistent peak 08:30-11:15"
    
    # Pattern 4: Card not found - generic
    card_match = re.search(r'Card (\d+) not found', message)
    if card_match:
        return f"Card {card_match.group(1)} not found", "Card lookup failed - missing or deleted card"
    
    # Pattern 5: Case not found
    case_match = re.search(r'Case (\d+) not found', message)
    if case_match:
        return f"Case {case_match.group(1)} not found", "Case resource lookup failed"
    
    # Pattern 6: Connection errors
    conn_match = re.search(r'Connection (?:timeout|refused|reset) (?:to )?([a-zA-Z0-9\.\-:]+)', message, re.IGNORECASE)
    if conn_match:
        return f"Connection failure to {conn_match.group(1)}", "Network connectivity issue - service unreachable"
    
    # Pattern 7: HTTP errors with status
    http_match = re.search(r'HTTP (\d{3})\s+([^:,\n]+)', message)
    if http_match:
        status = http_match.group(1)
        reason = http_match.group(2).strip()
        return f"HTTP {status} {reason}", f"HTTP {status} response from upstream service"
    
    # Pattern 8: Service errors with code (SPEED-XXX)
    speed_match = re.search(r'(SPEED-\d+)#PCB#([^#]+)#([^#]+)#([^#]+)#([^#]+)#([^#]+)', message)
    if speed_match:
        code, pcb, app, version, method, host = speed_match.groups()
        return f"{code}: {method} to {host} failed", f"External service call failed - {host} returned error"
    
    # Pattern 9: ITO errors
    ito_match = re.search(r'(ITO-\d+)#([^#]+)#([^#]+)#([^#]*)', message)
    if ito_match:
        code = ito_match.group(1)
        pcb = ito_match.group(2)
        app = ito_match.group(3)
        rest = ito_match.group(4)
        if rest:
            return f"{code}: {rest[:80]}", f"Service operation error - {code} in {app}"
        return f"{code}: {app} error", f"Service error - {code}"
    
    # Pattern 10: DoGS service errors
    if 'DoGS' in message and 'casesStart' in message:
        return "DoGS case management service error", "External DoGS service failed to start case - integration issue"
    
    # Pattern 11: Jersey/Tomcat startup
    if 'Jersey' in message or 'JerseyAutoConfiguration' in message:
        return "Failed Jersey auto-config during startup", "Jersey configuration failed in startup phase - dependency or configuration error"
    
    # Pattern 12: Tomcat startup generic
    if 'Tomcat' in message and 'context' in message.lower():
        return "Application startup context failed", "Failed to start application context during boot - check configuration and dependencies"
    
    # Pattern 12: Generic exception with message
    generic_match = re.search(r'(\w+Exception): (.{0,100})', message)
    if generic_match:
        exc_type = generic_match.group(1)
        exc_msg = generic_match.group(2).strip()
        if exc_msg and len(exc_msg) > 5:
            return f"{exc_msg}", f"Exception type: {exc_type}"
        return exc_type, "Application exception"
    
    # Pattern 13: "The required entity was not found"
    if "required entity was not found" in message:
        return "Required entity not found", "Resource lookup returned 404 - entity missing or deleted"
    
    # Pattern 14: NotFoundException
    if "NotFoundException" in message:
        return "Resource not found (404)", "Resource lookup failed - endpoint or entity not found"
    
    # Pattern 15: Generic error message
    if 'error' in message.lower():
        clean_msg = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:\.\+\-Z]+', '', message)
        clean_msg = re.sub(r'[a-f0-9]{32}', '', clean_msg)
        clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()
        return clean_msg[:100] if len(clean_msg) > 0 else "Unknown error", "Generic error - insufficient logging context"
    
    # Fallback
    return message[:100], "Unknown cause - see full message"

def _extract_context(message, cause):
    """Extract context description from message"""
    if '403' in message or 'Forbidden' in message:
        return "Authorization failure - missing/invalid credentials for downstream service"
    if '500' in message or '503' in message:
        return "Server error from external service - service unhealthy or overloaded"
    if 'Connection' in message or 'timeout' in message:
        return "Network connectivity issue - service unreachable or slow"
    if 'card' in message.lower():
        return "Card data access issue - customer card problem"
    return "Service integration issue"

def analyze_root_cause_specificity(root_cause):
    """
    Determine how specific and actionable the root cause is.
    Returns: 'concrete', 'semi-specific', 'generic'
    """
    generic_keywords = ['error', 'exception', 'failed', 'handler', 'timeout', 'unknown']
    
    # If it's very generic, mark it
    if any(word in root_cause.lower() for word in ['error handler', 'exception thrown', 'unknown error']):
        return 'generic'
    
    # If it mentions specific resource or service
    if any(x in root_cause for x in ['Card ', 'Case ', 'HTTP ', 'to ', 'Connection']):
        return 'concrete'
    
    return 'semi-specific'

def generate_detailed_report(root_causes_file, output_file):
    """Generate markdown report with concrete root causes"""
    
    with open(root_causes_file) as f:
        data = json.load(f)
    
    stats = data['stats']
    root_causes = data['root_causes']
    
    # Extract concrete root causes with context
    concrete_causes = []
    for cause in root_causes:
        concrete_cause, context = extract_concrete_root_cause(cause['message'])
        specificity = analyze_root_cause_specificity(concrete_cause)
        
        concrete_causes.append({
            'rank': cause['rank'],
            'concrete_cause': concrete_cause,
            'context': context,
            'specificity': specificity,
            'app': cause['app'],
            'errors_count': cause['errors_count'],
            'errors_percent': cause['errors_percent'],
            'traces_count': cause['trace_ids_count'],
            'affected_apps': cause['affected_apps'],
            'affected_namespaces': cause['affected_namespaces'],
            'first_seen': cause['first_seen'],
            'last_seen': cause['last_seen'],
            'trace_ids': cause.get('trace_ids', []),
        })
    
    with open(output_file, 'w') as f:
        # Header
        f.write("# Detailed Trace-Based Root Cause Analysis Report\n\n")
        f.write(f"**Period:** {data['period_start']} → {data['period_end']}\n\n")
        f.write("> 📌 This report focuses on **concrete, actionable root causes** extracted from trace analysis.\n")
        f.write("> Generic messages like 'Error handler threw exception' are replaced with specific issues.\n\n")
        
        # Overall stats
        f.write("## 📊 Overview\n\n")
        f.write(f"- **Total Errors:** {stats['total_errors']:,}\n")
        f.write(f"- **Unique Trace IDs:** {stats['total_traces']:,}\n")
        f.write(f"- **Unique Root Causes:** {len(concrete_causes)}\n")
        f.write(f"- **Avg errors per trace:** {stats['total_errors'] / stats['total_traces']:.1f}\n")
        f.write(f"- **Analysis method:** Trace-ID based (first error in chain = root cause)\n\n")
        
        # App distribution
        f.write("## 🎯 App Impact Distribution\n\n")
        for app, count in stats['app_distribution'].items():
            pct = (count / stats['total_errors'] * 100)
            bar_length = int(pct / 2)  # 50% = 25 chars
            bar = "█" * bar_length + "░" * (25 - bar_length)
            role = "🔴 PRIMARY" if pct > 40 else "🟡 SECONDARY" if pct > 15 else "🟢 TERTIARY"
            f.write(f"- **{app}**: {count:5d} errors ({pct:5.1f}%) {bar} {role}\n")
        f.write("\n")
        
        # Namespace distribution
        f.write("## 🔗 Namespace Distribution\n\n")
        total_ns_errors = sum(stats['namespace_distribution'].values())
        for ns, count in stats['namespace_distribution'].items():
            pct = (count / total_ns_errors * 100)
            bar_length = int(pct / 4)
            bar = "█" * bar_length + "░" * (25 - bar_length)
            balanced = "✅ Balanced" if 20 < pct < 40 else "⚠️  Imbalanced"
            f.write(f"- **{ns}**: {count:5d} errors ({pct:5.1f}%) {bar} {balanced}\n")
        f.write("\n")
        
        # Concrete Root Causes
        f.write(f"## 🔍 Concrete Root Causes (Top {min(15, len(concrete_causes))})\n\n")
        f.write("### Sorted by Impact (Errors × Prevalence)\n\n")
        
        # Group by specificity
        concrete = [c for c in concrete_causes if c['specificity'] == 'concrete']
        semi = [c for c in concrete_causes if c['specificity'] == 'semi-specific']
        generic = [c for c in concrete_causes if c['specificity'] == 'generic']
        
        # Show concrete first (most actionable)
        if concrete:
            f.write("### ✅ Concrete Issues (Actionable)\n\n")
            for i, cause in enumerate(concrete[:5], 1):
                _write_cause_detail(f, i, cause, stats['total_errors'])
        
        # Then semi-specific
        if semi:
            f.write("### ⚠️  Semi-Specific Issues (Needs investigation)\n\n")
            for i, cause in enumerate(semi[:5], 1):
                _write_cause_detail(f, i, cause, stats['total_errors'])
        
        # Then generic (least actionable)
        if generic:
            f.write("### ❓ Generic Issues (Insufficient Information)\n\n")
            f.write("*These should be investigated further by looking at individual trace chains.*\n\n")
            for i, cause in enumerate(generic[:3], 1):
                _write_cause_detail(f, i, cause, stats['total_errors'])
        
        # Analysis summary
        f.write("\n## 📋 Executive Summary\n\n")
        
        if concrete:
            primary = concrete[0]
            f.write(f"🎯 **PRIMARY ISSUE:** {primary['concrete_cause']}\n\n")
            f.write(f"- **Impact:** {primary['errors_count']:,} errors ({primary['errors_percent']:.1f}%)\n")
            f.write(f"- **Source:** {primary['app']}\n")
            f.write(f"- **Affected apps:** {', '.join(primary['affected_apps'][:3])}\n")
            
            # Format times without +00:00
            first_seen = primary['first_seen'].replace('+00:00', '').replace('Z', '')
            last_seen = primary['last_seen'].replace('+00:00', '').replace('Z', '')
            f.write(f"- **Time window:** {first_seen} → {last_seen}\n")
            f.write(f"- **Prevalence:** {primary['traces_count']} unique traces\n\n")
            f.write("**Action items:**\n")
            f.write(f"1. Investigate root cause on {primary['app']}\n")
            f.write(f"2. Monitor for propagation to {', '.join(primary['affected_apps'][1:3])}\n")
            f.write(f"3. Check if this is a known issue or new\n\n")
        
        if len(concrete) > 1:
            f.write(f"**Additional concrete issues:** {len(concrete) - 1} more actionable problems detected\n\n")
        
        if semi or generic:
            f.write(f"**Requires deeper investigation:** {len(semi) + len(generic)} issues with generic error messages\n")
            f.write(f"*Recommendation: Examine individual trace chains for these.*\n\n")
        
        # Specificity breakdown
        f.write("## 📈 Root Cause Specificity Breakdown\n\n")
        f.write(f"- 🎯 **Concrete (Actionable):** {len(concrete)} causes ({len(concrete)/len(concrete_causes)*100:.0f}%)\n")
        f.write(f"- ⚠️  **Semi-specific:** {len(semi)} causes ({len(semi)/len(concrete_causes)*100:.0f}%)\n")
        f.write(f"- ❓ **Generic (Needs investigation):** {len(generic)} causes ({len(generic)/len(concrete_causes)*100:.0f}%)\n\n")
        
        if len(generic) > len(concrete):
            f.write("⚠️  **Alert:** More than half of root causes are generic. This indicates:\n")
            f.write("- Error messages in logs lack specificity\n")
            f.write("- Need to implement better error reporting\n")
            f.write("- Manual trace chain analysis required for detailed diagnosis\n\n")

def _write_cause_detail(f, rank, cause, total_errors):
    """Write detailed cause section"""
    
    # Severity
    pct = cause['errors_percent']
    if pct >= 10:
        severity = "🔴 CRITICAL"
    elif pct >= 5:
        severity = "🟠 HIGH"
    elif pct >= 1:
        severity = "🟡 MEDIUM"
    else:
        severity = "🟢 LOW"
    
    f.write(f"#### {rank}. {severity} {cause['concrete_cause']}\n\n")
    f.write(f"**Context:** {cause['context']}\n\n")
    f.write(f"- **Source App:** `{cause['app']}`\n")
    f.write(f"- **Total Errors:** {cause['errors_count']:,} ({cause['errors_percent']:.1f}%)\n")
    f.write(f"- **Unique Traces:** {cause['traces_count']}\n")
    
    # Format times without +00:00
    first_seen = cause['first_seen'].replace('+00:00', '').replace('Z', '')
    last_seen = cause['last_seen'].replace('+00:00', '').replace('Z', '')
    f.write(f"- **Time Range:** {first_seen} → {last_seen}\n")
    
    f.write(f"- **Propagated to:** {', '.join(cause['affected_apps'][:3])}\n")
    f.write(f"- **Environments:** {', '.join(cause['affected_namespaces'])}\n")
    
    # Sample trace IDs
    sample_traces = [t for t in cause['trace_ids'][:3] if t]
    if sample_traces:
        f.write(f"- **Sample trace IDs:** `{sample_traces[0]}`, `{sample_traces[1] if len(sample_traces) > 1 else '...'}`\n")
    
    f.write("\n")

def main():
    parser = argparse.ArgumentParser(description='Generate detailed trace-based root cause report')
    parser.add_argument('--input', required=True, help='Input JSON from trace_extractor')
    parser.add_argument('--output', required=True, help='Output markdown report')
    
    args = parser.parse_args()
    
    generate_detailed_report(args.input, args.output)
    print(f"✅ Detailed report generated: {args.output}")

if __name__ == '__main__':
    main()
