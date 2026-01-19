"""Patch pro trends.py - přidání namespace breakdown"""

# Najdi část kde se vytváří ErrorPattern
print("""
V trends.py najdi:

        pattern = ErrorPattern(
            fingerprint=normalized[:50],
            error_code=error_code,
            message_sample=error_list[0]['message'][:150],
            count=extrapolated_count,
            first_seen=first_ts,
            last_seen=last_ts,
            affected_apps=apps[:5],
            status="recurring" if (last_ts - first_ts).days > 1 else "new"
        )

NAHRAĎ ZA:

        # Namespace breakdown
        namespaces = {}
        for e in error_list:
            ns = e.get('namespace', 'unknown')
            namespaces[ns] = namespaces.get(ns, 0) + 1
        
        # Extrapolate namespace counts
        ns_extrapolated = {}
        for ns, count in namespaces.items():
            ns_extrapolated[ns] = int((count / len(errors)) * total) if len(errors) > 0 else count
        
        pattern = ErrorPattern(
            fingerprint=normalized[:50],
            error_code=error_code,
            message_sample=error_list[0]['message'][:150],
            count=extrapolated_count,
            first_seen=first_ts,
            last_seen=last_ts,
            affected_apps=apps[:5],
            affected_namespaces=ns_extrapolated,
            status="recurring" if (last_ts - first_ts).days > 1 else "new"
        )
""")
