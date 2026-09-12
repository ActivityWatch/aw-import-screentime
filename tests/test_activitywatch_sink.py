from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests
from aw_core.models import Event

import aw_import_screentime.__main__ as mod
from aw_import_screentime.__main__ import ActivityWatchSink


UTC = timezone.utc


def make_event(
    timestamp: datetime,
    duration_seconds: float,
    app: str,
    *,
    title: str | None = None,
) -> Event:
    data = {"app": app}
    if title is not None:
        data["title"] = title
    return Event(
        timestamp=timestamp,
        duration=timedelta(seconds=duration_seconds),
        data=data,
    )


class FakeActivityWatchClient:
    def __init__(self, existing_events: dict[str, list[Event]] | None = None) -> None:
        self.events_by_bucket = existing_events or {}
        self.get_events_calls: list[tuple[str, datetime, datetime]] = []
        self.insert_events_calls: list[tuple[str, list[Event]]] = []

    def get_events(
        self,
        bucket_id: str,
        limit: int = -1,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Event]:
        assert limit == -1
        assert start is not None
        assert end is not None
        self.get_events_calls.append((bucket_id, start, end))
        return list(self.events_by_bucket.get(bucket_id, []))

    def insert_events(self, bucket_id: str, events: list[Event]) -> None:
        self.insert_events_calls.append((bucket_id, list(events)))
        self.events_by_bucket.setdefault(bucket_id, []).extend(events)


def test_emit_inserts_all_events_when_bucket_is_empty() -> None:
    bucket = "bucket-empty"
    client = FakeActivityWatchClient()
    sink = ActivityWatchSink(client)
    events = [
        make_event(datetime(2026, 5, 6, 12, 0, tzinfo=UTC), 60, "com.example.one"),
        make_event(datetime(2026, 5, 6, 12, 1, tzinfo=UTC), 30, "com.example.two"),
    ]

    inserted = sink.emit(bucket, events)

    assert inserted == 2
    assert len(client.insert_events_calls) == 1
    assert [event.data["app"] for event in client.insert_events_calls[0][1]] == [
        "com.example.one",
        "com.example.two",
    ]


def test_emit_skips_existing_duplicates_and_only_inserts_new_events() -> None:
    bucket = "bucket-dedupe"
    duplicate = make_event(
        datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        60,
        "com.example.duplicate",
    )
    new_event = make_event(
        datetime(2026, 5, 6, 12, 2, tzinfo=UTC),
        45,
        "com.example.new",
    )
    client = FakeActivityWatchClient(existing_events={bucket: [duplicate]})
    sink = ActivityWatchSink(client)

    inserted = sink.emit(bucket, [duplicate, new_event])

    assert inserted == 1
    assert len(client.insert_events_calls) == 1
    inserted_batch = client.insert_events_calls[0][1]
    assert len(inserted_batch) == 1
    assert inserted_batch[0].data["app"] == "com.example.new"
    queried_bucket, query_start, query_end = client.get_events_calls[0]
    assert queried_bucket == bucket
    assert query_start == duplicate.timestamp
    assert query_end == new_event.timestamp + new_event.duration


def test_emit_dedupes_when_only_title_changes() -> None:
    bucket = "bucket-title"
    existing = make_event(
        datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        90,
        "com.example.app",
    )
    retitled = make_event(
        existing.timestamp,
        90,
        "com.example.app",
        title="Human Friendly Name",
    )
    client = FakeActivityWatchClient(existing_events={bucket: [existing]})
    sink = ActivityWatchSink(client)

    inserted = sink.emit(bucket, [retitled])

    assert inserted == 0
    assert client.insert_events_calls == []


class FlakySink:
    """Sink whose ensure_bucket fails a set number of times per device."""

    def __init__(self, failures: dict[str, list[Exception]]) -> None:
        self.failures = {dev: list(errs) for dev, errs in failures.items()}
        self.calls: list[str] = []
        self.client = SimpleNamespace(server_address="http://127.0.0.1:5666")

    def ensure_bucket(self, device_id: str) -> str:
        self.calls.append(device_id)
        pending = self.failures.get(device_id)
        if pending:
            raise pending.pop(0)
        return f"bucket-{device_id}"

    def emit(self, bucket: str, events: list[Event]) -> int:  # pragma: no cover
        raise AssertionError("not used")


def test_ensure_buckets_blocking_returns_immediately_when_server_is_up() -> None:
    sink = FlakySink({})
    slept: list[float] = []

    buckets = mod.ensure_buckets_blocking(
        sink, ["a", "b"], retry_delay_seconds=5.0, sleep=slept.append
    )

    assert buckets == {"a": "bucket-a", "b": "bucket-b"}
    assert sink.calls == ["a", "b"]
    assert slept == []


def test_ensure_buckets_blocking_waits_for_server_and_only_retries_pending() -> None:
    sink = FlakySink(
        {
            "b": [
                requests.ConnectionError("refused"),
                requests.ConnectionError("refused"),
            ]
        }
    )
    slept: list[float] = []

    buckets = mod.ensure_buckets_blocking(
        sink,
        ["a", "b"],
        retry_delay_seconds=5.0,
        max_delay_seconds=8.0,
        sleep=slept.append,
    )

    assert buckets == {"a": "bucket-a", "b": "bucket-b"}
    # "a" succeeded on the first attempt and is never re-created.
    assert sink.calls == ["a", "b", "b", "b"]
    # Exponential backoff, capped by max_delay_seconds.
    assert slept == [5.0, 8.0]


def test_ensure_buckets_blocking_retries_server_errors() -> None:
    response = SimpleNamespace(status_code=503)
    sink = FlakySink({"a": [requests.HTTPError("starting", response=response)]})
    slept: list[float] = []

    buckets = mod.ensure_buckets_blocking(
        sink, ["a"], retry_delay_seconds=1.0, sleep=slept.append
    )

    assert buckets == {"a": "bucket-a"}
    assert slept == [1.0]


def test_ensure_buckets_blocking_raises_on_non_transient_error() -> None:
    response = SimpleNamespace(status_code=400)
    error = requests.HTTPError("bad bucket id", response=response)
    sink = FlakySink({"a": [error]})
    slept: list[float] = []

    with pytest.raises(requests.HTTPError):
        mod.ensure_buckets_blocking(
            sink, ["a"], retry_delay_seconds=1.0, sleep=slept.append
        )

    assert sink.calls == ["a"]
    assert slept == []
