"""Test pattern detector lokálně"""
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

from app.services.pattern_detector import pattern_detector

# Test messages
messages = [
    "Error occurred with Card id 12345",
    "Error occurred with Card id 67890",
    "ServiceBusinessException: timeout",
    "ServiceBusinessException: connection refused",
    "Queued event 111 was not processed",
    "Queued event 222 was not processed",
]

print("=== PATTERN DETECTION TEST ===\n")

for msg in messages:
    normalized = pattern_detector.normalize_message(msg)
    error_code = pattern_detector.extract_error_code(msg)
    card_id = pattern_detector.extract_card_id(msg)
    
    print(f"Original:   {msg}")
    print(f"Normalized: {normalized}")
    print(f"Error code: {error_code}")
    print(f"Card ID:    {card_id}")
    print()

# Test clustering
errors = [{'message': msg} for msg in messages]
clusters = pattern_detector.cluster_errors(errors)

print("\n=== CLUSTERS ===")
for pattern, items in clusters.items():
    print(f"\nPattern: {pattern[:80]}")
    print(f"Count: {len(items)}")
    print(f"Messages:")
    for item in items:
        print(f"  - {item['message']}")
