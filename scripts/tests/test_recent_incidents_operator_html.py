from scripts import recent_incidents_publisher as publisher


def test_operator_report_renders_structured_and_escaped_confluence_html():
    report_data = {
        'header': ('2026-08-25 08:00 - 2026-08-25 08:15', 'now', 'run-1'),
        'has_summary': True,
        'executive_summary': (
            'Cause families: 1\n'
            '  - Actionable technical: 1\n\n'
            'Impact and evidence coverage:\n'
            '  - Raw ERROR lines: 11\n'
            '  - Operation occurrences: 1\n\n'
            'Counts are current-period facts.'
        ),
        'has_details': True,
        'problem_details': (
            '-' * 50 + '\n'
            '#1 [TECHNICAL FAILURE] <script>alert(1)</script>\n'
            + '-' * 50 + '\n'
            '  Root application: bl-pcb-v1\n'
            '  Assessment: TECHNICAL FAILURE (high confidence)\n'
            '  Operation: repairCard\n'
            '  Outward status: 500\n\n'
            '  Impact (current period):\n'
            '    Unique operations: 1\n'
            '    Operation count evidence: root_span (high confidence)\n'
            '    Raw ERROR lines: 11\n'
            '    Logging amplification: 11.0x\n\n'
            '  Evidence:\n'
            '    Representative trace: trace-lock\n\n'
            '  Next action:\n'
            '    Inspect concurrent updates.\n'
        ),
    }

    report_data['problem_details'] = report_data['problem_details'].replace(
        '-' * 50,
        '\u2500' * 50,
    )
    html = publisher.convert_to_html(report_data)

    assert '<pre' not in html
    assert '<table' in html
    assert 'Current Cause Families' in html
    assert 'Inspect concurrent updates.' in html
    assert '<script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
