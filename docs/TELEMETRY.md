# Telemetry Context

Jednotná normalizační vrstva pro extrakci a validaci telemetry dat z Elasticsearch eventů.

## Účel

1. Oddělení raw ES eventu od interního incident modelu
2. Konzistentní přístup ke všem důležitým polím
3. Zabránění chybnému fallbacku (např. `-v1` místo verze)

## Pravidla

### Povoleno

| Pole | Zdroj | Formát |
|------|-------|--------|
| `application_version` | `application.version` | X.Y.Z (semantic version) |
| `deployment_label` | `application.name` | string (může obsahovat -v1) |
| `environment` | odvozeno z namespace | prod/uat/sit/dev |
| `trace_id` | `traceId` | string |
| `span_id` | `spanId` | string |
| `parent_span_id` | `parentId` | string |

### Zakázáno

- Parsování verze z názvu služby (`-v1`, `-v2`)
- Build number jako verze
- SDK/API version
- Odvozování clusteru z namespace
- LLM / ML inference

## Datové struktury

### IncidentTelemetryContext

```python
@dataclass
class IncidentTelemetryContext:
    deployment_label: str                 # application.name
    application_version: Optional[str]    # X.Y.Z nebo None
    environment: Environment              # prod/uat/sit/dev
    namespace: str
    trace_id: Optional[str]
    span_id: Optional[str]
    parent_span_id: Optional[str]
    event_timestamp: Optional[datetime]
```

### TraceContext

```python
@dataclass
class TraceContext:
    trace_id: str
    deployment_labels: Set[str]           # Services v trace
    namespaces: Set[str]
    first_event_ts: Optional[datetime]
    last_event_ts: Optional[datetime]
    root_deployment: Optional[str]        # Nejstarší event
    event_count: int

    @property
    def is_propagated(self) -> bool:
        """True pokud trace obsahuje více než 1 service."""
        return len(self.deployment_labels) > 1
```

### PropagationInfo

```python
@dataclass
class PropagationInfo:
    propagated: bool                      # Incident se šíří
    root_deployment: Optional[str]        # Kde začal
    affected_deployments: Set[str]        # Všechny affected
    propagation_time_sec: Optional[float] # Čas propagace
    trace_count: int                      # Počet propagated traces
```

## Použití

### Základní extrakce

```python
from core import create_telemetry_context

event = {
    'application.name': 'my-service-v1',
    'application.version': '3.5.0',
    'kubernetes.namespace': 'pcb-prod-cz',
    'traceId': 'abc123',
    'spanId': 'span456',
}

ctx = create_telemetry_context(event)

print(ctx.deployment_label)      # 'my-service-v1'
print(ctx.application_version)   # '3.5.0'
print(ctx.environment)           # Environment.PROD
print(ctx.has_trace)             # True
print(ctx.has_version)           # True
```

### Detekce propagace

```python
from core import aggregate_trace_contexts, detect_propagation

# Agreguj eventy podle trace_id
trace_contexts = aggregate_trace_contexts(telemetry_contexts)

# Detekuj propagaci
propagation = detect_propagation(trace_contexts)

if propagation.propagated:
    print(f"Root: {propagation.root_deployment}")
    print(f"Affected: {propagation.affected_deployments}")
    print(f"Time: {propagation.propagation_time_sec}s")
```

## Podporované formáty eventů

### Flat keys (ES format)

```json
{
  "application.name": "my-service-v1",
  "application.version": "3.5.0",
  "kubernetes.namespace": "pcb-prod-cz",
  "traceId": "abc123"
}
```

### Nested objects

```json
{
  "application": {
    "name": "my-service-v1",
    "version": "3.5.0"
  },
  "kubernetes": {
    "namespace": "pcb-prod-cz"
  }
}
```

### Simple (fallback)

```json
{
  "application": "my-service-v1",
  "namespace": "pcb-prod-cz"
}
```

## Odvození environment

| Pattern v namespace | Environment |
|--------------------|-------------|
| `-prod-`, `.prod.`, `_prod_` | prod |
| `-uat-`, `.uat.`, `_uat_` | uat |
| `-sit-`, `.sit.`, `_sit_` | sit |
| `-dev-`, `.dev.`, `_dev_` | dev |
| (jiné) | unknown |

## Validace verze

Verze je validní pouze pokud:

1. Existuje v poli `application.version`
2. Odpovídá formátu X.Y.Z (semantic version)

```python
# Validní verze
"3.5.0"       # ✓
"1.0.0"       # ✓
"v3.5.0"      # ✓ (prefix 'v' se odstraní)

# Nevalidní verze (vrací None)
"v1"          # ✗ deployment label suffix
"build-123"   # ✗ build number
"1.0"         # ✗ chybí patch version
```

## Integrace s registry

Registry odděluje:

```python
problem.deployments_seen = {'my-app-v1', 'my-app-v2'}  # Z application.name
problem.app_versions_seen = {'3.5.0', '3.5.1'}         # Z application.version
```

## Export

Tabulkové exporty obsahují oddělené sloupce:

```csv
deployment_labels,app_versions
"my-app-v1, my-app-v2","3.5.0, 3.5.1"
```
