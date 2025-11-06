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

Additional Context:
{context}

Similar Past Incidents:
{similar_incidents}

Provide analysis in JSON format with:
- root_cause: Brief explanation of what caused the error
- recommendations: List of 2-3 specific actions to fix/prevent
- confidence: Your confidence level (0-100)
- severity: critical/high/medium/low
"""


def format_analyze_prompt(
    app_name: str,
    namespace: str,
    error_message: str,
    count: int,
    stack_trace: str = "",
    context: str = "",
    similar_incidents: str = "None found"
) -> str:
    """Format error analysis prompt."""
    return ANALYZE_ERROR_TEMPLATE.format(
        app_name=app_name,
        namespace=namespace,
        error_message=error_message,
        count=count,
        stack_trace=stack_trace or "Not available",
        context=context or "No additional context",
        similar_incidents=similar_incidents
    )
