import sys

# Read file
with open('/home/jvsete/git/sas/ai-log-analyzer/analyze_period.py', 'r') as f:
    lines = f.readlines()

# Find and replace the last section
new_lines = []
for i, line in enumerate(lines):
    if line.strip() == "parser.add_argument('--batch-size', type=int, default=5000, help='Batch size (default: 5000)')":
        new_lines.append(line)
        new_lines.append("    parser.add_argument('--with-intelligent', action='store_true', help='Enable intelligent analysis (optional)')\n")
    elif line.strip().startswith("success = analyze_period(args.date_from, args.date_to, args.output, args.batch_size)"):
        new_lines.append("    success = analyze_period(args.date_from, args.date_to, args.output, args.batch_size, args.with_intelligent)\n")
    else:
        new_lines.append(line)

# Write back
with open('/home/jvsete/git/sas/ai-log-analyzer/analyze_period.py', 'w') as f:
    f.writelines(new_lines)

print("✅ Fixed arguments")
