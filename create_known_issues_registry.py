#!/usr/bin/env python3

"""
KNOWN ISSUES REGISTRY BUILDER
============================
Vytváří strukturovanou databázi známých problémů z orchestračního výstupu.
Umožňuje:
  1. Filtrování nových errors proti známým problémům
  2. Tracking повторujících se issues
  3. Podklady pro JIRA tickets
  4. Machine learning pattern matching
"""

import json
import os
import sys
import hashlib
from datetime import datetime
from collections import defaultdict
from pathlib import Path

class KnownIssuesRegistry:
    def __init__(self, registry_path='data/known_issues_registry.json'):
        self.registry_path = registry_path
        self.registry = self._load_registry()
    
    def _load_registry(self):
        """Načti existující registry nebo vytvoř nový"""
        if os.path.exists(self.registry_path):
            with open(self.registry_path) as f:
                return json.load(f)
        return {
            "metadata": {
                "version": "1.0",
                "created": datetime.utcnow().isoformat(),
                "last_updated": datetime.utcnow().isoformat(),
                "total_known_issues": 0
            },
            "issues": {}
        }
    
    def _generate_issue_id(self, root_cause_msg, exception_type):
        """Generuj unikátní ID pro issue"""
        combined = f"{root_cause_msg}:{exception_type}"
        return hashlib.md5(combined.encode()).hexdigest()[:12]
    
    def add_issue_from_orchestration(self, cause_data, cause_rank, frequency):
        """Přidej issue z orchestračního výstupu"""
        
        msg = cause_data.get('message', 'Unknown')
        exc_type = cause_data.get('exception_type', 'Unknown')
        affected_apps = cause_data.get('affected_apps', [])
        
        issue_id = self._generate_issue_id(msg, exc_type)
        
        # Pokud issue již existuje, updatuj jej
        if issue_id in self.registry['issues']:
            issue = self.registry['issues'][issue_id]
            issue['last_seen'] = datetime.utcnow().isoformat()
            issue['occurrences'] += 1
            issue['frequency_history'].append({
                'date': datetime.utcnow().isoformat(),
                'count': frequency
            })
        else:
            # Nový issue
            issue = {
                'id': issue_id,
                'rank': cause_rank,
                'message': msg,
                'exception_type': exc_type,
                'affected_apps': affected_apps,
                'first_seen': datetime.utcnow().isoformat(),
                'last_seen': datetime.utcnow().isoformat(),
                'occurrences': 1,
                'frequency_history': [
                    {
                        'date': datetime.utcnow().isoformat(),
                        'count': frequency
                    }
                ],
                'severity': self._assess_severity(frequency, len(affected_apps)),
                'jira_ticket': None,
                'status': 'open',  # open, resolved, wontfix, duplicate
                'notes': []
            }
            self.registry['issues'][issue_id] = issue
        
        return issue_id
    
    def _assess_severity(self, frequency, num_apps):
        """Ohodnoť severity na základě frekvence a počtu apů"""
        if frequency > 100 or num_apps > 5:
            return 'CRITICAL'
        elif frequency > 50 or num_apps > 3:
            return 'HIGH'
        elif frequency > 10:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def get_jira_template(self, issue_id):
        """Vygeneruj JIRA ticket template"""
        issue = self.registry['issues'].get(issue_id)
        if not issue:
            return None
        
        apps_str = ', '.join(issue['affected_apps'][:5])
        template = f"""
JIRA TICKET TEMPLATE
====================

Title: [{issue['severity']}] {issue['message'][:80]}

Type: Bug
Priority: {self._jira_priority(issue['severity'])}
Assignee: [Team]

Description:
-----------
**Problem:**
{issue['message']}

**Exception Type:**
{issue['exception_type']}

**Affected Applications:**
{apps_str}

**Frequency:**
{issue['occurrences']} occurrences tracked
Latest: {issue['last_seen']}

**Known Cause:**
[To be filled by investigation team]

**Proposed Solution:**
[To be filled by development team]

**Status:**
{issue['status']}
"""
        return template
    
    def _jira_priority(self, severity):
        """Převeď severity na JIRA priority"""
        mapping = {
            'CRITICAL': 'Highest',
            'HIGH': 'High',
            'MEDIUM': 'Medium',
            'LOW': 'Low'
        }
        return mapping.get(severity, 'Medium')
    
    def save(self):
        """Ulož registry"""
        os.makedirs(os.path.dirname(self.registry_path) or '.', exist_ok=True)
        self.registry['metadata']['last_updated'] = datetime.utcnow().isoformat()
        self.registry['metadata']['total_known_issues'] = len(self.registry['issues'])
        
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)
        
        print(f"✅ Registry uložen: {self.registry_path}")
        return self.registry_path
    
    def print_summary(self):
        """Vytiskni přehled"""
        issues = self.registry['issues']
        
        print("\n" + "="*70)
        print("📋 KNOWN ISSUES REGISTRY SUMMARY")
        print("="*70)
        print(f"\nTotal Known Issues: {len(issues)}")
        
        # By severity
        by_severity = defaultdict(list)
        for issue_id, issue in issues.items():
            by_severity[issue['severity']].append(issue)
        
        print("\n📊 By Severity:")
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            count = len(by_severity[severity])
            if count > 0:
                print(f"  {severity}: {count}")
        
        # Top issues
        print("\n🔴 TOP 10 ISSUES (by occurrences):")
        sorted_issues = sorted(issues.items(), 
                              key=lambda x: x[1]['occurrences'], 
                              reverse=True)
        
        for rank, (issue_id, issue) in enumerate(sorted_issues[:10], 1):
            msg = issue['message'][:70]
            apps = ', '.join(issue['affected_apps'][:2])
            print(f"\n{rank}. [{issue['severity']}] {msg}")
            print(f"   ID: {issue_id}")
            print(f"   Occurrences: {issue['occurrences']}")
            print(f"   Apps: {apps}")
            if issue['jira_ticket']:
                print(f"   JIRA: {issue['jira_ticket']}")
        
        print("\n" + "="*70)


def main():
    """Hlavní workflow"""
    
    if len(sys.argv) < 2:
        print("Usage: python3 create_known_issues_registry.py <orchestration_output.json>")
        print("\nExample:")
        print("  python3 create_known_issues_registry.py test_orchestration_1764762448.json")
        sys.exit(1)
    
    orch_file = sys.argv[1]
    
    if not os.path.exists(orch_file):
        print(f"❌ Soubor nenalezen: {orch_file}")
        sys.exit(1)
    
    print(f"📂 Čtu orchestrační output: {orch_file}")
    
    with open(orch_file) as f:
        orch_data = json.load(f)
    
    # Vytvoř/načti registry
    registry = KnownIssuesRegistry()
    
    # Extrahuj root causes z reportu
    report = orch_data.get('markdown_report', '')
    root_causes_analysis = orch_data.get('root_causes_analysis', {})
    
    # Parsuj root causes z markdown reportu
    print(f"📊 Parsuju root causes...")
    
    # Jednoduchý parser - najdi "#### N." řádky
    lines = report.split('\n')
    rank = 0
    current_issue = None
    
    for i, line in enumerate(lines):
        # Detekuj root cause (#### N. Severity Message)
        if line.startswith('#### '):
            rank += 1
            # Parsuj titulek
            # Format: "#### 1. 🔴 CRITICAL Message here"
            parts = line[5:].split(' ', 2)  # Skip "#### "
            if len(parts) >= 2:
                msg = parts[-1]  # Posledníí část je message
                
                # Najdi exception type v následujících řádcích
                exc_type = 'Unknown'
                for j in range(i+1, min(i+5, len(lines))):
                    if 'Exception type:' in lines[j]:
                        exc_type = lines[j].split('Exception type:')[1].strip()
                        break
                
                # Najdi aplikace
                apps = []
                for j in range(i+1, min(i+10, len(lines))):
                    if 'Source App:' in lines[j]:
                        app = lines[j].split('Source App:')[1].strip()
                        app = app.strip('`').strip()
                        if app != 'unknown':
                            apps.append(app)
                        break
                
                # Najdi frekvenci
                freq = 0
                for j in range(i+1, min(i+20, len(lines))):
                    if 'Total Errors:' in lines[j]:
                        freq_str = lines[j].split('Total Errors:')[1].split('(')[0].strip()
                        try:
                            freq = int(freq_str)
                        except:
                            pass
                        break
                
                cause_data = {
                    'message': msg,
                    'exception_type': exc_type,
                    'affected_apps': apps
                }
                
                issue_id = registry.add_issue_from_orchestration(cause_data, rank, freq)
                print(f"  ✅ Issue #{rank}: {msg[:60]} ({freq} errors)")
    
    # Ulož registry
    registry.save()
    registry.print_summary()
    
    # Vygeneruj JIRA template pro top issues
    print("\n📌 JIRA TICKET TEMPLATES (Top 3):")
    sorted_issues = sorted(registry.registry['issues'].items(),
                          key=lambda x: x[1]['occurrences'],
                          reverse=True)
    
    for issue_id, issue in sorted_issues[:3]:
        template = registry.get_jira_template(issue_id)
        print(template)


if __name__ == '__main__':
    main()
