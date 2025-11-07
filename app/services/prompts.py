"""Prompt templates for log analysis."""

SYSTEM_PROMPT = """You are an expert SRE analyzing application logs.
Provide concise root cause analysis and actionable recommendations.
Be specific and practical. Output valid JSON."""

ANALYZE_ERROR_TEMPLATE = """Analyze this error:

Application: {app_name}
Namespace: {namespace}
Error Message: {error_message}
Occurrences: {count} times
Stack Trace: {stack_trace}

Trace Information:
- Trace ID: {trace_id}
- Span ID: {span_id}
- Pod: {pod_name}
- Timestamp: {timestamp}

Related Logs (from same trace):
{related_logs}

Additional Context:
{context}

Similar Past Incidents:
{similar_incidents}

Provide detailed analysis in JSON format with:
- root_cause: Specific explanation based on trace and related logs
- recommendations: List of 3-5 actionable steps with priority
- confidence: Your confidence level (0-100)
- severity: critical/high/medium/low
- trace_analysis: Summary of what the trace shows
"""


def format_analyze_prompt(
    app_name: str,
    namespace: str,
    error_message: str,
    count: int,
    stack_trace: str = "",
    context: str = "",
    similar_incidents: str = "None found",
    trace_id: str = None,
    span_id: str = None,
    pod_name: str = None,
    timestamp: str = None,
    related_logs: str = ""
) -> str:
    """Format error analysis prompt."""
    return ANALYZE_ERROR_TEMPLATE.format(
        app_name=app_name,
        namespace=namespace,
        error_message=error_message,
        count=count,
        stack_trace=stack_trace or "Not available",
        trace_id=trace_id or "Not available",
        span_id=span_id or "Not available",
        pod_name=pod_name or "Not available",
        timestamp=timestamp or "Not available",
        related_logs=related_logs or "No related logs found",
        context=context or "No additional context",
        similar_incidents=similar_incidents
    )
