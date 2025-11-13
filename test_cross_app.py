#!/usr/bin/env python3
"""Test cross-app correlation - sledování error chainů"""
import json
import re
from collections import defaultdict

def find_case_and_card_ids(errors):
    """Extrahuj Case a Card IDs z error zpráv"""
    case_groups = defaultdict(list)
    card_groups = defaultdict(list)
    
    for e in errors:
        msg = e.get('message', '')
        
        # Extract Case IDs (Case 12345, case-123, etc)
        case_matches = re.findall(r'[Cc]ase[:\s-]+(\d+)', msg)
        for case_id in case_matches:
            case_groups[case_id].append(e)
        
        # Extract Card IDs
        card_matches = re.findall(r'[Cc]ard[:\s-]+(\d+)', msg)
        for card_id in card_matches:
            card_groups[card_id].append(e)
    
    return case_groups, card_groups

def test_cross_app(data_file):
    """Test cross-app correlation"""
    print("=" * 80)
    print(f"TEST: Cross-App Correlation ({data_file})")
    print("=" * 80)
    
    # Load data
    with open(data_file) as f:
        data = json.load(f)
    
    errors = data.get('errors', [])
    print(f"\n📊 Total errors: {len(errors)}")
    
    # Find Case/Card IDs
    case_groups, card_groups = find_case_and_card_ids(errors)
    
    print(f"\n🔍 ID Tracking:")
    print(f"  Cases found: {len(case_groups)}")
    print(f"  Cards found: {len(card_groups)}")
    
    # Analyze Cases affecting multiple apps
    print(f"\n📱 Cases affecting multiple apps:")
    multi_app_cases = []
    
    for case_id, case_errors in case_groups.items():
        apps = set(e.get('app_name', 'unknown') for e in case_errors)
        namespaces = set(e.get('namespace', 'unknown') for e in case_errors)
        
        if len(apps) > 1 or len(case_errors) >= 3:
            multi_app_cases.append({
                'id': case_id,
                'errors': case_errors,
                'apps': apps,
                'namespaces': namespaces
            })
    
    multi_app_cases.sort(key=lambda x: len(x['errors']), reverse=True)
    
    if multi_app_cases:
        for i, case in enumerate(multi_app_cases[:5], 1):
            print(f"\n  {i}. Case {case['id']}")
            print(f"     Errors: {len(case['errors'])}")
            print(f"     Apps: {', '.join(case['apps']) if case['apps'] != {'unknown'} else 'N/A'}")
            print(f"     Namespaces: {', '.join(list(case['namespaces'])[:3])}")
            
            # Show sample messages
            samples = case['errors'][:2]
            for s in samples:
                msg = s.get('message', '')[:80]
                print(f"       - {msg}...")
    else:
        print("  ⚠️  No cases affecting multiple apps found")
    
    # Analyze Cards
    print(f"\n💳 Cards with multiple errors:")
    multi_error_cards = []
    
    for card_id, card_errors in card_groups.items():
        if len(card_errors) >= 2:
            apps = set(e.get('app_name', 'unknown') for e in card_errors)
            multi_error_cards.append({
                'id': card_id,
                'errors': card_errors,
                'apps': apps
            })
    
    multi_error_cards.sort(key=lambda x: len(x['errors']), reverse=True)
    
    if multi_error_cards:
        for i, card in enumerate(multi_error_cards[:5], 1):
            print(f"\n  {i}. Card {card['id']}")
            print(f"     Errors: {len(card['errors'])}")
            print(f"     Apps: {', '.join(card['apps']) if card['apps'] != {'unknown'} else 'N/A'}")
    else:
        print("  ⚠️  No cards with multiple errors found")
    
    print()

def main():
    test_files = [
        'data/batches/2025-11-12/batch_02_0830-0900.json',
        'data/last_hour_v2.json',
    ]
    
    for test_file in test_files:
        try:
            test_cross_app(test_file)
            break
        except FileNotFoundError:
            continue

if __name__ == '__main__':
    main()
