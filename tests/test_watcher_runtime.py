from pathlib import Path
from types import SimpleNamespace

import aw_import_screentime.__main__ as mod


def make_focus_event(bundle_id: str, cf_absolute_time: float, in_foreground: bool):
    return SimpleNamespace(
        bundle_id=bundle_id,
        cf_absolute_time=cf_absolute_time,
        in_foreground=in_foreground,
    )


def test_read_new_events_for_device_catches_unread_events_on_startup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    older = tmp_path / "older.segb"
    newer = tmp_path / "newer.segb"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")

    unread = make_focus_event("com.example.app", 150.0, True)
    state = mod.DeviceState(last_file=None, last_cf=100.0)

    monkeypatch.setattr(mod, "tail_device_files", lambda dev, limit: [older, newer])

    def fake_iter(path: Path):
        if path == newer:
            yield unread
        else:
            if False:
                yield None

    monkeypatch.setattr(mod, "iter_app_in_focus_events", fake_iter)

    result = mod.read_new_events_for_device("device-1", state)

    assert result.events == [unread]
    assert result.new_last_file == newer
    assert result.new_last_cf == 150.0
    assert result.dirty is True


def test_determine_watch_scan_targets_uses_timeout_as_safety_rescan() -> None:
    targets = mod.determine_watch_scan_targets(
        woke=False,
        drained_changed=set(),
        all_device_ids=["device-1", "device-2"],
    )

    assert targets == {"device-1", "device-2"}


def test_determine_watch_scan_targets_skips_spurious_wake_without_changes() -> None:
    targets = mod.determine_watch_scan_targets(
        woke=True,
        drained_changed=set(),
        all_device_ids=["device-1", "device-2"],
    )

    assert targets == set()
