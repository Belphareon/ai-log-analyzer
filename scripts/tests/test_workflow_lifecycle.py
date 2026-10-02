from datetime import datetime, timezone

from scripts.analysis.workflow_lifecycle import (
    LifecycleFetchStats,
    analyze_workflow_events,
    parse_lifecycle_event,
)


TOPIC = "cluster-k8s_prod_0927-in"
NAMESPACE = "pcb-prod-01-app"
CLUSTER = "elasticsearch.kb.cz"


def _document(message, timestamp, event_id):
    return {
        "_index": "cluster-app_pcb-2026.09.24",
        "_id": event_id,
        "_source": {
            "@timestamp": timestamp,
            "topic": TOPIC,
            "kubernetes": {
                "namespace": NAMESPACE,
                "pod": {"name": "bl-pcb-client-rainbow-status-v1-a"},
            },
            "application": {"name": "bl-pcb-client-rainbow-status-v1"},
            "traceId": "f845e956aa3e02f3ddc1ab92f01089b1",
            "level": "INFO",
            "message": message,
        },
    }


def _event(message, timestamp, event_id):
    event = parse_lifecycle_event(_document(message, timestamp, event_id), CLUSTER)
    assert event is not None
    return event


def _complete_stats(complete=True):
    return LifecycleFetchStats(
        source_cluster=CLUSTER,
        source_index="cluster-app_pcb-*",
        scope=f"{TOPIC}|{NAMESPACE}",
        expected_count=12,
        fetched_count=12,
        processed_count=12,
        query_count=2,
        complete=complete,
        reason=None if complete else "record cap 12",
    )


def test_complete_predecessor_evidence_produces_high_confidence_hot_loop():
    start = "2026-09-24T23:18:01.000Z"
    event_message = (
        "Start processing of queued event EventProcessingQueue(queueEventId=6467528, "
        "entityId='117818068', entityType=CLIENT, eventId=CLIENT_CARDS_MIGRATION_117818068, "
        "type=CLIENT_CARDS_MIGRATION, sourceType=EVENT, createdAt=2026-09-25T01:07:55.681, "
        "processing=EventProcessing{status=PROCESSING, description='null', "
        "delayedTo=2026-09-25T01:17:55.728992, startAt=null, endAt=null, retryCount=0}, answer=null)."
    )
    blocked_message = (
        "There are prior unprocessed events for the entity CLIENT(117818068), this event "
        "6467528 CLIENT_CARDS_MIGRATION/CLIENT_CARDS_MIGRATION_117818068 for CLIENT(117818068) "
        "will be delayed. Prior events are [6467677 CLIENT_MIGRATION/CLIENT_MIGRATION_a for "
        "CLIENT(117818068), 6467678 CLIENT_MIGRATION/CLIENT_MIGRATION_a for CLIENT(117818068)]."
    )
    transition_message = (
        "Changing status of event CLIENT_CARDS_MIGRATION(6467528) of CLIENT(117818068) "
        "from PROCESSING to REGISTERED."
    )
    no_delay_message = (
        "Moving event CLIENT_CARDS_MIGRATION(6467528) of CLIENT(117818068) back to "
        "REGISTERED status, without delaying."
    )
    events = []
    for attempt in range(3):
        second = 1 + attempt
        events.extend([
            _event(event_message, f"2026-09-24T23:18:0{second}.000Z", f"start-{attempt}"),
            _event(blocked_message, f"2026-09-24T23:18:0{second}.010Z", f"blocked-{attempt}"),
            _event(transition_message, f"2026-09-24T23:18:0{second}.020Z", f"transition-{attempt}"),
            _event(no_delay_message, f"2026-09-24T23:18:0{second}.030Z", f"no-delay-{attempt}"),
        ])
    events.extend([
        _event(
            "Changing status of event CLIENT_MIGRATION(6467677) of CLIENT(117818068) from PROCESSING to COMPLETED.",
            "2026-09-24T23:20:22.643Z", "completed-1",
        ),
        _event(
            "Changing status of event CLIENT_MIGRATION(6467678) of CLIENT(117818068) from PROCESSING to COMPLETED.",
            "2026-09-24T23:20:22.786Z", "completed-2",
        ),
    ])

    incidents = analyze_workflow_events(
        events,
        _complete_stats(),
        datetime(2026, 9, 24, 23, 10, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 35, tzinfo=timezone.utc),
    )
    incident = next(item for item in incidents if item.identity.queue_event_id == "6467528")

    assert incident.loop_detected
    assert incident.confidence == "high"
    assert incident.alert_eligible
    assert incident.attempt_count == 3
    assert incident.processing_to_registered_count == 3
    assert incident.stale_delay_count == 3
    assert incident.predecessor_event_ids == ["6467677", "6467678"]
    assert incident.predecessor_completed_event_ids == ["6467677", "6467678"]


def test_incomplete_fetch_cannot_make_a_high_confidence_alert():
    event = _event(
        "Moving event CLIENT_CARDS_MIGRATION(6467528) of CLIENT(117818068) back to "
        "REGISTERED status, without delaying.",
        "2026-09-24T23:18:01.030Z", "partial-1",
    )
    incidents = analyze_workflow_events(
        [event],
        _complete_stats(complete=False),
        datetime(2026, 9, 24, 23, 10, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 35, tzinfo=timezone.utc),
    )

    assert incidents[0].incomplete
    assert not incidents[0].alert_eligible
    assert incidents[0].confidence != "high"