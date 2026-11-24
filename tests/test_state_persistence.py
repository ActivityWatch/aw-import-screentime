import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import aw_import_screentime.__main__ as mod


def make_focus_event(bundle_id: str, cf_absolute_time: float, in_foreground: bool):
    return SimpleNamespace(
        bundle_id=bundle_id,
        cf_absolute_time=cf_absolute_time,
        in_foreground=in_foreground,
    )


@pytest.fixture
def state_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "state"
    monkeypatch.setattr(mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(mod, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(mod, "LEGACY_STATE_FILE", tmp_path / "legacy-state.json")
    monkeypatch.setattr(mod.save_device_states, "_warned", False, raising=False)
    return state_dir / "state.json"


def test_failed_state_write_keeps_previous_state(
    state_paths: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod.save_device_states(
        {
            "device-1": mod.DeviceState(
                last_cf=500.0,
                open_interval=mod.OpenIntervalState("com.example.a", 480.0),
            )
        }
    )
    assert mod.load_device_states()["device-1"].last_cf == 500.0

    def dump_then_enospc(obj, f, *args, **kwargs):
        f.write('{"last_cf": {"device-1": 6')  # partial write, then disk full
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(mod.json, "dump", dump_then_enospc)
        mod.save_device_states({"device-1": mod.DeviceState(last_cf=600.0)})

    loaded = mod.load_device_states()
    assert loaded["device-1"].last_cf == 500.0
    assert loaded["device-1"].open_interval == mod.OpenIntervalState(
        "com.example.a", 480.0
    )
    assert list(state_paths.parent.iterdir()) == [state_paths]


def test_load_device_states_warns_on_corrupt_state_file(
    state_paths: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state_paths.parent.mkdir(parents=True)
    state_paths.write_text('{"last_cf": {"device-1": 6', encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger=mod.logger.name):
        assert mod.load_device_states() == {}

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "corrupt state file should be logged at WARNING"


def test_load_device_states_is_quiet_when_state_file_missing(
    state_paths: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=mod.logger.name):
        assert mod.load_device_states() == {}

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# --------------------------------------------------------------------------------------
# Harness that drives the real `watch` main loop with fakes
# --------------------------------------------------------------------------------------


class StopLoop(Exception):
    pass


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.client_hostname = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSink:
    def __init__(self, client, bucket_suffix=None):
        pass

    def ensure_bucket(self, device_id):
        return f"bucket-{device_id}"

    def emit(self, bucket_id, events):
        return len(events)


class FakeObserver:
    def schedule(self, handler, path, recursive=False):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


def run_watch(tmp_path, monkeypatch, ids, *, read_fn, extra_args=()):
    streams = tmp_path / "streams"
    for device_id in ids:
        (streams / device_id).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "STREAMS_DIR", streams)
    monkeypatch.setattr(mod, "get_device_ids", lambda db, platform=2: list(ids))
    monkeypatch.setattr(mod, "ActivityWatchClient", FakeClient)
    monkeypatch.setattr(mod, "ActivityWatchSink", FakeSink)
    monkeypatch.setattr(mod, "Observer", FakeObserver)
    monkeypatch.setattr(mod, "WATCH_SAFETY_RESCAN_SECONDS", 0.01)
    monkeypatch.setattr(
        mod, "enrich_events_with_titles", lambda events, storefronts: None
    )
    monkeypatch.setattr(mod, "read_new_events_for_device", read_fn)
    return CliRunner().invoke(
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


def test_watch_with_device_filter_preserves_other_devices_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state_paths: Path
) -> None:
    mod.save_device_states(
        {
            "device-a": mod.DeviceState(last_cf=100.0),
            "device-b": mod.DeviceState(
                last_cf=777.0,
                open_interval=mod.OpenIntervalState("com.example.b", 700.0),
            ),
        }
    )
    calls = {"n": 0}

    def read_fn(device_id, state, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return mod.NewEvents(
                [make_focus_event("com.example.a", 200.0, True)],
                tmp_path / "segb-file",
                200.0,
                True,
            )
        raise StopLoop()

    result = run_watch(
        tmp_path,
        monkeypatch,
        ["device-a", "device-b"],
        read_fn=read_fn,
        extra_args=["--device", "device-a"],
    )

    assert isinstance(result.exception, StopLoop), repr(result.exception)
    loaded = mod.load_device_states()
    assert loaded["device-a"].last_cf == 200.0
    assert loaded["device-a"].open_interval == mod.OpenIntervalState(
        "com.example.a", 200.0
    )
    assert loaded["device-b"].last_cf == 777.0
    assert loaded["device-b"].open_interval == mod.OpenIntervalState(
        "com.example.b", 700.0
    )
    # Sanity: the on-disk payload is still a well-formed state file.
    assert set(json.loads(state_paths.read_text())["devices"]) == {
        "device-a",
        "device-b",
    }
