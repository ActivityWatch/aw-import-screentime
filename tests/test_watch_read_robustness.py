"""Regression tests for watch-mode file reading: catch-up, vanished and unreadable files."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import aw_import_screentime.__main__ as mod


def ev(bundle, cf, fg):
    return SimpleNamespace(bundle_id=bundle, cf_absolute_time=cf, in_foreground=fg)


@pytest.fixture
def state_paths(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(mod, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(mod, "LEGACY_STATE_FILE", tmp_path / "legacy.json")
    monkeypatch.setattr(mod.save_device_states, "_warned", False, raising=False)
    return state_dir / "state.json"


def make_stream_files(tmp_path, monkeypatch, dev, contents):
    """contents: list of (name, [events]) oldest -> newest (by mtime)."""
    streams = tmp_path / "streams"
    d = streams / dev
    d.mkdir(parents=True)
    by_path = {}
    for i, (name, events) in enumerate(contents):
        p = d / name
        p.write_bytes(b"x")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
        by_path[p] = events
    monkeypatch.setattr(mod, "STREAMS_DIR", streams)
    monkeypatch.setattr(
        mod, "iter_app_in_focus_events", lambda p: iter(by_path[Path(p)])
    )
    return d


# ---------------------------------------------------------------------------
# 1. Catch-up only looks at the 2 newest files but still advances the watermark
# ---------------------------------------------------------------------------
def test_catch_up_reads_all_files_newer_than_watermark(tmp_path, monkeypatch):
    # State from the previous run: watermark 100, app A still in foreground since 90.
    state = mod.DeviceState(
        last_file=None,
        last_cf=100.0,
        open_interval=mod.OpenIntervalState("com.a", 90.0),
    )
    # While the watcher was down, Biome rotated through three files.
    make_stream_files(
        tmp_path,
        monkeypatch,
        "dev",
        [
            ("f1", [ev("com.a", 150.0, False)]),  # A lost focus at 150
            ("f2", [ev("com.b", 1000.0, True)]),
            ("f3", [ev("com.b", 1100.0, False)]),
        ],
    )
    res = mod.read_new_events_for_device("dev", state)
    cfs = sorted(e.cf_absolute_time for e in res.events)
    stitched, _ = mod.stitch_intervals_with_state(
        res.events, tzinfo=mod.UTC, initial_open_interval=state.open_interval
    )
    a = [s for s in stitched if s.data["app"] == "com.a"]
    # Master: cfs == [1000, 1100] (150 silently skipped, watermark -> 1100) and
    # A is stitched as 90..1000 = 910s instead of 60s.
    assert 150.0 in cfs
    assert a[0].duration.total_seconds() == 60.0


# ---------------------------------------------------------------------------
# Harness to drive the real `watch` main loop with fakes
# ---------------------------------------------------------------------------
class StopLoop(Exception):
    pass


class FakeClient:
    def __init__(self, *a, **k):
        self.client_hostname = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSink:
    emitted: list = []

    def __init__(self, client, bucket_suffix=None):
        pass

    def ensure_bucket(self, dev):
        return f"bucket-{dev}"

    def emit(self, bucket, events):
        FakeSink.emitted.append((bucket, list(events)))
        return len(events)


def run_watch(tmp_path, monkeypatch, ids, *, observer_cls, read_fn=None, extra_args=()):
    streams = tmp_path / "streams"
    for d in ids:
        (streams / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "STREAMS_DIR", streams)
    monkeypatch.setattr(mod, "get_device_ids", lambda db, platform=2: list(ids))
    monkeypatch.setattr(mod, "ActivityWatchClient", FakeClient)
    monkeypatch.setattr(mod, "ActivityWatchSink", FakeSink)
    monkeypatch.setattr(mod, "Observer", observer_cls)
    monkeypatch.setattr(mod, "WATCH_SAFETY_RESCAN_SECONDS", 0.01)
    monkeypatch.setattr(
        mod, "enrich_events_with_titles", lambda events, storefronts: None
    )
    if read_fn is not None:
        monkeypatch.setattr(mod, "read_new_events_for_device", read_fn)
    FakeSink.emitted = []
    runner = CliRunner()
    return runner.invoke(
        mod.app,
        [
            "--config",
            str(tmp_path / "missing.toml"),
            "--log-level",
            "ERROR",
            "watch",
            *extra_args,
        ],
    )


def make_observer_cls(captured):
    class FakeObserver:
        def schedule(self, handler, path, recursive=False):
            captured.append((handler, path))

        def start(self):
            pass

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

    return FakeObserver


# ---------------------------------------------------------------------------
# 3. A moved event whose destination is outside the device dir kills the watcher
# ---------------------------------------------------------------------------
def test_moved_event_out_of_device_dir_does_not_crash_watcher(
    tmp_path, monkeypatch, state_paths
):
    captured = []
    calls = {"n": 0}

    def read_fn(dev, state, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            handler, path = captured[0]
            # e.g. Biome moving a SEGB file into a subdirectory such as tombstone/
            handler.on_any_event(
                SimpleNamespace(
                    is_directory=False,
                    src_path=f"{path}/12345",
                    dest_path=f"{path}/tombstone/12345",
                )
            )
        if calls["n"] >= 5:
            raise StopLoop()
        return mod.NewEvents([], None, None, False)

    result = run_watch(
        tmp_path,
        monkeypatch,
        ["dev"],
        observer_cls=make_observer_cls(captured),
        read_fn=read_fn,
    )
    # Master: result.exception is KeyError('tombstone') raised from runtimes[dev].
    assert isinstance(result.exception, StopLoop), repr(result.exception)


# ---------------------------------------------------------------------------
# 5. A file disappearing between iterdir() and the mtime sort kills the watcher
# ---------------------------------------------------------------------------
def test_file_deleted_during_enumeration_does_not_raise(tmp_path, monkeypatch):
    d = make_stream_files(
        tmp_path, monkeypatch, "dev", [("f1", [ev("com.a", 10.0, True)]), ("f2", [])]
    )
    gone = d / "f1"
    real_is_file = Path.is_file

    def is_file_then_delete(self):
        r = real_is_file(self)
        if self == gone and r:
            self.unlink()  # Biome prunes the file right after we looked at it
        return r

    monkeypatch.setattr(Path, "is_file", is_file_then_delete)
    # Master: FileNotFoundError from files.sort(key=lambda p: p.stat().st_mtime),
    # raised outside every try in read_new_events_for_device and the watch loop.
    mod.read_new_events_for_device("dev", mod.DeviceState())


# ---------------------------------------------------------------------------
# 6. One unreadable file in the tail window hides all events of the other file
# ---------------------------------------------------------------------------
def test_corrupt_older_file_does_not_hide_newest_events(tmp_path, monkeypatch):
    make_stream_files(
        tmp_path, monkeypatch, "dev", [("f1", []), ("f2", [ev("com.a", 200.0, True)])]
    )
    good = mod.iter_app_in_focus_events

    def iter_fn(p):
        if Path(p).name == "f1":
            raise ValueError("File is not a SEGB File")
        return good(p)

    monkeypatch.setattr(mod, "iter_app_in_focus_events", iter_fn)
    res = mod.read_new_events_for_device("dev", mod.DeviceState(last_cf=100.0))
    # Master: events == [] (whole scan discarded, logged at DEBUG; no retry scheduled).
    assert [e.cf_absolute_time for e in res.events] == [200.0]


def test_fresh_state_still_reads_only_tail_files(tmp_path, monkeypatch):
    # Without a persisted watermark the watcher must not import the whole history;
    # that is what `events import` is for.
    make_stream_files(
        tmp_path,
        monkeypatch,
        "dev",
        [
            ("f1", [ev("com.a", 10.0, True)]),
            ("f2", [ev("com.b", 20.0, True)]),
            ("f3", [ev("com.c", 30.0, True)]),
        ],
    )
    res = mod.read_new_events_for_device("dev", mod.DeviceState())
    assert sorted(e.cf_absolute_time for e in res.events) == [20.0, 30.0]


def test_unreadable_newest_file_defers_scan(tmp_path, monkeypatch):
    # The newest file may be mid-write; skipping it would advance the watermark
    # past events it still holds, so the scan is retried instead.
    make_stream_files(
        tmp_path, monkeypatch, "dev", [("f1", [ev("com.a", 200.0, True)]), ("f2", [])]
    )
    good = mod.iter_app_in_focus_events

    def iter_fn(p):
        if Path(p).name == "f2":
            raise ValueError("truncated trailer")
        return good(p)

    monkeypatch.setattr(mod, "iter_app_in_focus_events", iter_fn)
    res = mod.read_new_events_for_device("dev", mod.DeviceState(last_cf=100.0))
    assert res.events == []
    assert res.new_last_cf is None
