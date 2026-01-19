import re

with open('app/models/pattern.py', 'r') as f:
    content = f.read()

# Find and replace FindingPattern class
old_pattern = r'class FindingPattern\(Base\):.*?__tablename__ = "finding_patterns".*?finding_id = Column\(Integer, primary_key=True\)\s*pattern_id = Column\(Integer, primary_key=True\)'

new_pattern = '''class FindingPattern(Base):
    """Association table between findings and patterns."""

    __tablename__ = "finding_patterns"

    finding_id = Column(Integer, ForeignKey("findings.id"), primary_key=True)
    pattern_id = Column(Integer, ForeignKey("patterns.id"), primary_key=True)'''

content = re.sub(old_pattern, new_pattern, content, flags=re.DOTALL)

with open('app/models/pattern.py', 'w') as f:
    f.write(content)

print("Fixed FindingPattern foreign keys")
