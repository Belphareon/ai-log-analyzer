#!/usr/bin/env python3
import sys

# Read original
with open('/home/jvsete/git/sas/ai-log-analyzer/analyze_period.py', 'r') as f:
    content = f.read()

# 1. Update function signature
content = content.replace(
    'def analyze_period(date_from, date_to, output_file, batch_size=5000):',
    'def analyze_period(date_from, date_to, output_file, batch_size=5000, with_intelligent=False):'
)

# 2. Update initial print
content = content.replace(
    '''    print(f"\\n{Color.BOLD}🎯 AI Log Analyzer - Complete Pipeline{Color.END}")
    print(f"Period: {date_from} → {date_to}")
    print(f"Output: {output_file}\\n")''',
    '''    print(f"\\n{Color.BOLD}🎯 AI Log Analyzer - Complete Pipeline{Color.END}")
    print(f"Period: {date_from} → {date_to}")
    print(f"Output: {output_file}")
    if with_intelligent:
        print(f"Mode: WITH INTELLIGENT ANALYSIS ✨\\n")
    else:
        print(f"Mode: Standard (trace-based)\\n")'''
)

# 3. Add intelligent analysis after STEP 3
intelligent_code = '''
    # STEP 4 (OPTIONAL): Intelligent Analysis
    intelligent_analysis = None
    if with_intelligent:
        log_step("STEP 4/4+: Running Intelligent Analysis (optional)")
        intelligent_file = "/tmp/intelligent_analysis.json"
        if run_cmd(f"python3 intelligent_analysis.py --input {batch_file} --output {intelligent_file}", "Intelligent Analysis"):
            try:
                with open(intelligent_file) as f:
                    intelligent_analysis = json.load(f)
                log_ok("Intelligent analysis completed")
            except:
                log_err("Could not load intelligent analysis results")
        else:
            log_err("Intelligent analysis skipped")

    # STEP 5: Consolidate & Analyze
    log_step("STEP 5/4: Creating comprehensive analysis file" if with_intelligent else "STEP 4/4: Creating comprehensive analysis file")
'''

# Insert before "log_step("STEP 4/4: Creating comprehensive analysis file")"
old_step4 = '    log_step("STEP 4/4: Creating comprehensive analysis file")'
content = content.replace(old_step4, intelligent_code)

# 4. Add intelligent_analysis to output JSON
content = content.replace(
    '''    analysis_output = {
        "metadata": {
            "analysis_type": "Complete Trace-Based Root Cause Analysis",
            "period_start": date_from,
            "period_end": date_to,
            "generated_at": datetime.utcnow().isoformat(),
            "version": "1.0"
        },''',
    '''    analysis_output = {
        "metadata": {
            "analysis_type": "Complete Trace-Based Root Cause Analysis",
            "period_start": date_from,
            "period_end": date_to,
            "generated_at": datetime.utcnow().isoformat(),
            "version": "1.0",
            "intelligent_analysis_enabled": with_intelligent
        },'''
)

# Add intelligent_analysis to stats section
content = content.replace(
    '''        "markdown_report": report_content
    }''',
    '''        "markdown_report": report_content,
        "intelligent_analysis": intelligent_analysis
    }'''
)

# 5. Add CLI argument
content = content.replace(
    '''    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size (default: 5000)')

    args = parser.parse_args()
    success = analyze_period(args.date_from, args.date_to, args.output, args.batch_size)''',
    '''    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size (default: 5000)')
    parser.add_argument('--with-intelligent', action='store_true', help='Enable intelligent analysis (optional)')

    args = parser.parse_args()
    success = analyze_period(args.date_from, args.date_to, args.output, args.batch_size, args.with_intelligent)'''
)

# Write modified
with open('/home/jvsete/git/sas/ai-log-analyzer/analyze_period.py', 'w') as f:
    f.write(content)

print("✅ Patched successfully")
