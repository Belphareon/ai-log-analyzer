"""Bounded, fail-closed Elasticsearch fetch for workflow lifecycle evidence."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth
import urllib3

try:
    from analysis.workflow_lifecycle import LifecycleFetchStats, parse_lifecycle_event
    from core.fetch_unlimited import BASE_URL, ES_PASSWORD, ES_USER, INDICES
except ModuleNotFoundError:
    from scripts.analysis.workflow_lifecycle import LifecycleFetchStats, parse_lifecycle_event
    from scripts.core.fetch_unlimited import BASE_URL, ES_PASSWORD, ES_USER, INDICES


urllib3.disable_warnings()

_LIFECYCLE_PATTERNS = (
    "Start processing of queued event",
    "There are prior unprocessed events for the entity",
    "back to REGISTERED status, without delaying",
    "Changing status of event",
    "was processed successfully",
)
_SOURCE_FIELDS = (
    "@timestamp",
    "message",
    "level",
    "topic",
    "application.name",
    "service.name",
    "kubernetes.namespace",
    "kubernetes.pod.name",
    "traceId",
    "trace.id",
)


@dataclass(frozen=True)
class LifecycleScope:
    topic: str
    namespace: str

    @property
    def key(self) -> str:
        return f"{self.topic}|{self.namespace}"


@dataclass
class LifecycleProbeResult:
    scopes: List[LifecycleScope] = field(default_factory=list)
    expected_count: Optional[int] = None
    fetched_count: int = 0
    truncated: bool = False
    reason: Optional[str] = None


def _source_cluster() -> str:
    return urlparse(BASE_URL).netloc or BASE_URL


def _build_pattern_should() -> List[Dict[str, Any]]:
    return [{"match_phrase": {"message": pattern}} for pattern in _LIFECYCLE_PATTERNS]


def _scope_filter(scope: LifecycleScope, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    return [
        {"range": {"@timestamp": {"gte": date_from, "lt": date_to}}},
        {"term": {"topic": scope.topic}},
        {"term": {"kubernetes.namespace": scope.namespace}},
    ]


def _stats(scope: str) -> LifecycleFetchStats:
    return LifecycleFetchStats(
        source_cluster=_source_cluster(),
        source_index=INDICES,
        scope=scope,
    )


def _session() -> requests.Session:
    session = requests.Session()
    session.auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    session.verify = False
    session.trust_env = True
    return session


def probe_lifecycle(
    date_from: str,
    date_to: str,
    max_hits: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> LifecycleProbeResult:
    """Cheap all-level probe that discovers candidate topic/namespace scopes.

    A capped probe is deliberately allowed to be incomplete: it only selects
    scopes for the subsequent fail-closed context fetch and never emits alerts.
    """
    max_hits = max_hits or int(os.getenv("LIFECYCLE_PROBE_MAX_HITS", "200"))
    owns_session = session is None
    session = session or _session()
    try:
        body = {
            "size": max_hits,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [{"range": {"@timestamp": {"gte": date_from, "lt": date_to}}}],
                    "should": _build_pattern_should(),
                    "minimum_should_match": 1,
                }
            },
            "sort": [{"@timestamp": {"order": "asc"}}],
            "_source": ["topic", "kubernetes.namespace"],
        }
        response = session.post(f"{BASE_URL}/{INDICES}/_search", json=body, timeout=120)
        if response.status_code != 200:
            return LifecycleProbeResult(reason=f"Elasticsearch probe failed ({response.status_code})")
        data = response.json()
        total = data.get("hits", {}).get("total", 0)
        expected = int(total.get("value", 0) if isinstance(total, dict) else total or 0)
        scopes = []
        seen = set()
        for hit in data.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            topic = str(source.get("topic") or "")
            kubernetes = source.get("kubernetes") if isinstance(source.get("kubernetes"), dict) else {}
            namespace = str(kubernetes.get("namespace") or source.get("kubernetes.namespace") or "")
            if topic and namespace and (topic, namespace) not in seen:
                scopes.append(LifecycleScope(topic, namespace))
                seen.add((topic, namespace))
        fetched = len(data.get("hits", {}).get("hits", []))
        return LifecycleProbeResult(
            scopes=scopes,
            expected_count=expected,
            fetched_count=fetched,
            truncated=expected > fetched,
            reason=(f"probe capped at {max_hits}" if expected > fetched else None),
        )
    except requests.RequestException as error:
        return LifecycleProbeResult(reason=f"Elasticsearch probe failed: {error.__class__.__name__}")
    finally:
        if owns_session:
            session.close()


def _fetch_query(
    session: requests.Session,
    query: Dict[str, Any],
    stats: LifecycleFetchStats,
    batch_size: int,
    max_records: int,
) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    pit_id: Optional[str] = None
    search_after = None
    try:
        pit_response = session.post(f"{BASE_URL}/{INDICES}/_pit?keep_alive=5m", timeout=120)
        if pit_response.status_code != 200:
            stats.reason = f"PIT open failed ({pit_response.status_code})"
            return documents
        pit_id = pit_response.json().get("id")
        if not pit_id:
            stats.reason = "PIT open response did not contain an id"
            return documents

        while True:
            body = dict(query)
            body.update({
                "size": batch_size,
                "sort": [
                    {"@timestamp": {"order": "asc"}},
                    {"_shard_doc": {"order": "asc"}},
                ],
                "_source": list(_SOURCE_FIELDS),
                "pit": {"id": pit_id, "keep_alive": "5m"},
                "track_total_hits": stats.expected_count is None,
            })
            if search_after:
                body["search_after"] = search_after
            response = session.post(f"{BASE_URL}/_search", json=body, timeout=120)
            stats.query_count += 1
            if response.status_code != 200:
                stats.reason = f"Elasticsearch search failed ({response.status_code})"
                return documents
            data = response.json()
            pit_id = data.get("pit_id", pit_id)
            if stats.expected_count is None:
                total = data.get("hits", {}).get("total", 0)
                stats.expected_count = int(total.get("value", 0) if isinstance(total, dict) else total or 0)
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break
            remaining = max_records - len(documents)
            if remaining <= 0:
                stats.truncated = True
                stats.reason = f"record cap {max_records}"
                break
            selected = hits[:remaining]
            documents.extend(selected)
            if len(selected) < len(hits):
                stats.truncated = True
                stats.reason = f"record cap {max_records}"
                break
            if len(documents) >= max_records and len(hits) == batch_size:
                stats.truncated = True
                stats.reason = f"record cap {max_records}"
                break
            if len(hits) < batch_size:
                break
            search_after = hits[-1].get("sort")
    except requests.RequestException as error:
        stats.reason = f"Elasticsearch request failed: {error.__class__.__name__}"
    finally:
        if pit_id:
            try:
                session.delete(f"{BASE_URL}/_pit", json={"id": pit_id}, timeout=30)
            except requests.RequestException:
                pass
    stats.fetched_count += len(documents)
    return documents


def _lifecycle_query(scope: LifecycleScope, date_from: str, date_to: str) -> Dict[str, Any]:
    return {
        "query": {
            "bool": {
                "filter": _scope_filter(scope, date_from, date_to),
                "should": _build_pattern_should(),
                "minimum_should_match": 1,
            }
        }
    }


def _predecessor_query(
    scope: LifecycleScope,
    predecessor_ids: Sequence[str],
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    phrases = [
        {"match_phrase": {"message": predecessor_id}}
        for predecessor_id in predecessor_ids
    ]
    return {
        "query": {
            "bool": {
                "filter": _scope_filter(scope, date_from, date_to),
                "should": phrases,
                "minimum_should_match": 1,
            }
        }
    }


def fetch_lifecycle_context(
    scopes: Iterable[LifecycleScope],
    date_from: str,
    date_to: str,
    batch_size: Optional[int] = None,
    max_records_per_query: Optional[int] = None,
    max_predecessor_ids: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> Tuple[List[Dict[str, Any]], LifecycleFetchStats]:
    """Fetch candidate lifecycle messages and then their predecessor evidence.

    The aggregated result is complete only when every scope and predecessor
    query reconciles `expected_count == fetched_count` without a cap or error.
    """
    batch_size = batch_size or int(os.getenv("LIFECYCLE_FETCH_BATCH_SIZE", "1000"))
    max_records_per_query = max_records_per_query or int(
        os.getenv("LIFECYCLE_MAX_RECORDS_PER_QUERY", "50000")
    )
    max_predecessor_ids = max_predecessor_ids or int(
        os.getenv("LIFECYCLE_MAX_PREDECESSOR_IDS", "500")
    )
    if max_predecessor_ids < 1:
        raise ValueError("max_predecessor_ids must be at least 1")
    scope_list = list(dict.fromkeys(scopes))
    stats = _stats(",".join(scope.key for scope in scope_list))
    if not scope_list:
        stats.reason = "no lifecycle scopes"
        return [], stats
    if not ES_PASSWORD:
        stats.reason = "Elasticsearch credentials are unavailable"
        return [], stats

    owns_session = session is None
    session = session or _session()
    documents: List[Dict[str, Any]] = []
    predecessor_ids: Dict[LifecycleScope, set[str]] = defaultdict(set)
    all_expected = 0
    all_fetched = 0
    complete = True
    try:
        for scope in scope_list:
            query_stats = _stats(scope.key)
            fetched = _fetch_query(
                session, _lifecycle_query(scope, date_from, date_to), query_stats,
                batch_size, max_records_per_query,
            )
            documents.extend(fetched)
            all_expected += query_stats.expected_count or 0
            all_fetched += query_stats.fetched_count
            stats.query_count += query_stats.query_count
            complete = complete and query_stats.reason is None and not query_stats.truncated and query_stats.expected_count == query_stats.fetched_count
            for document in fetched:
                event = parse_lifecycle_event(document, _source_cluster())
                if event:
                    predecessor_ids[scope].update(event.predecessor_event_ids)

        for scope, ids in predecessor_ids.items():
            if not ids:
                continue
            selected_ids = sorted(ids)
            if len(selected_ids) > max_predecessor_ids:
                selected_ids = selected_ids[:max_predecessor_ids]
                stats.truncated = True
                stats.reason = (
                    f"predecessor id cap {max_predecessor_ids} for {scope.key}"
                )
                complete = False
            query_stats = _stats(f"{scope.key}|predecessors")
            fetched = _fetch_query(
                session,
                _predecessor_query(scope, selected_ids, date_from, date_to),
                query_stats,
                batch_size,
                max_records_per_query,
            )
            documents.extend(fetched)
            all_expected += query_stats.expected_count or 0
            all_fetched += query_stats.fetched_count
            complete = complete and query_stats.reason is None and not query_stats.truncated and query_stats.expected_count == query_stats.fetched_count
            stats.query_count += query_stats.query_count
    finally:
        if owns_session:
            session.close()

    deduplicated = []
    seen = set()
    for document in documents:
        key = (document.get("_index"), document.get("_id"))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(document)
    stats.expected_count = all_expected
    stats.fetched_count = all_fetched
    stats.processed_count = len(deduplicated)
    stats.complete = complete and all_expected == all_fetched
    if not stats.complete and not stats.reason:
        stats.reason = "one or more lifecycle scope queries were incomplete"
    return deduplicated, stats