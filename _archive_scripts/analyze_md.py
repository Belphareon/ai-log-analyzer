import os
from datetime import datetime

md_files = {
    'SESSION_PROGRESS.md': 'Session progress (2025-11-12 afternoon, feedback endpoint)',
    'PROJECT_STATUS.md': 'Project status snapshot (2025-11-12, Phase 2 planning)',
    'TRACE_ANALYSIS_PROCEDURE.md': 'Trace analysis procedure (2025-11-13, design doc)',
    'E2E_TEST_RESULTS.md': 'E2E test results (2025-11-12, API testing)',
    'REAL_DATA_TEST_PLAN.md': 'Real data test plan (2025-11-12, batch testing)',
    'AUDIT_JUSTIFICATION.md': 'Audit justification (2025-11-18, cleanup docs)',
    'PHASE_3_SUMMARY.md': 'Phase 3 summary (2025-11-18, phase recap)',
    'KNOWN_ISSUES_DESIGN.md': 'Known issues design (2025-11-19, registry design)',
    'DEPLOYMENT.md': 'Deployment guide (2025-11-12, K8s deployment)',
    'README_SCRIPTS.md': 'Script documentation (2025-11-13, script reference)',
    'README.md': 'Main README (2025-11-12, comprehensive guide)',
    'HOW_TO_USE.md': 'Operational manual (2025-12-02, updated quick ref)',
    'DAILY_SESSION_2025_12_02.md': 'Daily session log (2025-12-02, today session)',
    'COMPLETED_LOG.md': 'Completed tasks (2025-12-02, task history)',
    'working_progress.md': 'Working progress (2025-12-02, current work)',
    'todo_final.md': 'Final TODO (2025-11-18, master TODO)',
}

print("# Analýza .md souborů\n")
print("## Kategorizace:\n")

print("### AKTUÁLNÍ (Červen 2025):")
print("- working_progress.md - KEEP (aktuální pracovní progress)")
print("- COMPLETED_LOG.md - KEEP (task history, stále relevantní)")
print("- HOW_TO_USE.md - KEEP (operační manuál, updated)")
print("- DAILY_SESSION_2025_12_02.md - KEEP (dnešní session log)")
print("- todo_final.md - KEEP (master TODO)\n")

print("### STARÉ SESSION LOGS (Listopad 2025):")
print("- SESSION_PROGRESS.md - DELETE (outdated, session 2025-11-12)")
print("- PROJECT_STATUS.md - DELETE (outdated snapshot, 2025-11-12)")
print("- DAILY_SESSION_2025_12_02.md - KEEP (today, fresh)\n")

print("### DESIGN & PROCEDURY (Listopad 2025):")
print("- TRACE_ANALYSIS_PROCEDURE.md - MERGE (into trace_report_detailed.py docs)")
print("- KNOWN_ISSUES_DESIGN.md - KEEP (still relevant)")
print("- PHASE_3_SUMMARY.md - ARCHIVE (phase recap, done)\n")

print("### TESTOVÁNÍ (Listopad 2025):")
print("- E2E_TEST_RESULTS.md - ARCHIVE (old test, have new tests)")
print("- REAL_DATA_TEST_PLAN.md - ARCHIVE (plan done, results in COMPLETED_LOG)\n")

print("### DEPLOYMENT & CONFIG (Listopad 2025):")
print("- DEPLOYMENT.md - KEEP (still valid for K8s)")
print("- README.md - KEEP (main documentation)")
print("- README_SCRIPTS.md - KEEP (script reference)\n")

print("### AUDIT (Listopad 2025):")
print("- AUDIT_JUSTIFICATION.md - DELETE (cleanup doc, no longer needed)\n")

