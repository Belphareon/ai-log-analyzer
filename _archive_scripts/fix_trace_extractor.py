import sys

# Načti trace_extractor.py
with open('trace_extractor.py', 'r') as f:
    content = f.read()

# Fix 1: Změň error.get('app') na error.get('application')
old_line1 = "                app = error.get('app', 'unknown')"
new_line1 = "                app = error.get('application', 'unknown')"
content = content.replace(old_line1, new_line1)

# Fix 2: Změň error.get('namespace') na error.get('cluster') nebo lepší defaultní
old_line2 = "                ns = error.get('namespace', 'unknown')"
new_line2 = "                ns = error.get('cluster', 'unknown')"  # Cluster je nejbližší náhrada za namespace
content = content.replace(old_line2, new_line2)

# Ulož
with open('trace_extractor.py', 'w') as f:
    f.write(content)

print("✅ Fixed trace_extractor.py:")
print(f"  - Changed 'app' -> 'application'")
print(f"  - Changed 'namespace' -> 'cluster'")

