import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import aw_import_screentime.__main__ as mod


UTC = timezone.utc


def make_focus_event(bundle_id: str, cf_absolute_time: float, in_foreground: bool):
    return SimpleNamespace(
        bundle_id=bundle_id,
        cf_absolute_time=cf_absolute_time,
        in_foreground=in_foreground,
    )


def test_stitch_intervals_with_state_closes_persisted_interval_on_loss() -> None:
    stitched, open_interval = mod.stitch_intervals_with_state(
        [make_focus_event("com.example.app", 120.0, False)],
        tzinfo=UTC,
        initial_open_interval=mod.OpenIntervalState(
            bundle_id="com.example.app",
            start_cf=100.0,
        ),
    )

    assert open_interval is None
    assert len(stitched) == 1
    assert stitched[0].data["app"] == "com.example.app"
    assert stitched[0].timestamp == datetime.fromtimestamp(
        100.0 + mod.APPLE_EPOCH_OFFSET,
        tz=UTC,
    )
    assert stitched[0].duration.total_seconds() == 20.0


def test_stitch_intervals_with_state_carries_forward_open_interval() -> None:
    stitched, open_interval = mod.stitch_intervals_with_state(
        [make_focus_event("com.example.app", 250.0, True)],
        tzinfo=UTC,
    )

    assert stitched == []
    assert open_interval == mod.OpenIntervalState(
        bundle_id="com.example.app",
        start_cf=250.0,
    )


def test_load_device_states_supports_legacy_last_cf_format(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_file = state_dir / "state.json"
    state_dir.mkdir(parents=True)
    state_file.write_text(json.dumps({"last_cf": {"device-1": 123.0}}), encoding="utf-8")

    original_state_dir = mod.STATE_DIR
    original_state_file = mod.STATE_FILE
    original_legacy_state_file = mod.LEGACY_STATE_FILE
    try:
        mod.STATE_DIR = state_dir
        mod.STATE_FILE = state_file
        mod.LEGACY_STATE_FILE = tmp_path / "legacy-state.json"
        loaded = mod.load_device_states()
    finally:
        mod.STATE_DIR = original_state_dir
        mod.STATE_FILE = original_state_file
        mod.LEGACY_STATE_FILE = original_legacy_state_file

    assert loaded["device-1"].last_cf == 123.0
    assert loaded["device-1"].open_interval is None


def test_save_and_load_device_states_round_trip_open_interval(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_file = state_dir / "state.json"

    original_state_dir = mod.STATE_DIR
    original_state_file = mod.STATE_FILE
    original_legacy_state_file = mod.LEGACY_STATE_FILE
    try:
        mod.STATE_DIR = state_dir
        mod.STATE_FILE = state_file
        mod.LEGACY_STATE_FILE = tmp_path / "legacy-state.json"
        mod.save_device_states(
            {
                "device-1": mod.DeviceState(
                    last_cf=456.0,
                    open_interval=mod.OpenIntervalState(
                        bundle_id="com.example.persisted",
                        start_cf=450.0,
                    ),
                )
            }
        )
        loaded = mod.load_device_states()
    finally:
        mod.STATE_DIR = original_state_dir
        mod.STATE_FILE = original_state_file
        mod.LEGACY_STATE_FILE = original_legacy_state_file

    assert loaded["device-1"].last_cf == 456.0
    assert loaded["device-1"].open_interval == mod.OpenIntervalState(
        bundle_id="com.example.persisted",
        start_cf=450.0,
    )
