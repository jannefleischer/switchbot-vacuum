"""Tests for the task record evaluation, using the shapes the S20 cloud returns."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.switchbot_vacuum.clean_history import (
    MAX_STORED_TASKS,
    compact_record,
    is_cleaning_task,
    last_task_summary,
    merge_records,
    room_activity,
    task_rooms,
)


def _rooms_task(rooms, start=1_000_000, clean=600_000, result="success", task_id="t1"):
    return {
        "taskID": task_id,
        "userID": "secret-user",
        "timestamp": start,
        "duration": clean + 60_000,
        "cleanTime": clean,
        "taskArea": 9,
        "action": "clean_rooms",
        "result": result,
        "source": "app",
        "actionParam": {
            "rooms": [{"room_id": r, "mode": {"type": t}} for r, t in rooms],
        },
    }


class TestFiltering:
    def test_aborted_run_is_ignored(self):
        assert not is_cleaning_task(_rooms_task([("R", "sweep")], clean=0, result="app_stop"))

    def test_stopped_run_that_cleaned_counts(self):
        assert is_cleaning_task(_rooms_task([("R", "sweep")], result="app_stop"))

    def test_non_cleaning_action_is_ignored(self):
        task = {"action": "backing_to_charge", "cleanTime": 600_000, "actionParam": None}
        assert not is_cleaning_task(task)
        assert task_rooms(task) == []


class TestRoomActivity:
    def test_sweep_only_counts_as_vacuumed(self):
        activity = room_activity([_rooms_task([("R", "sweep")])])
        assert activity["R"] == {"vacuumed": 1_660_000}

    def test_sweep_mop_counts_for_both(self):
        entry = room_activity([_rooms_task([("R", "sweep_mop")])])["R"]
        assert entry["vacuumed"] == entry["mopped"] == 1_660_000

    def test_first_sweep_then_mop_counts_for_both(self):
        assert set(room_activity([_rooms_task([("R", "first_sweep_then_mop")])])["R"]) == {
            "vacuumed",
            "mopped",
        }

    def test_mode_is_per_room(self):
        activity = room_activity([_rooms_task([("A", "sweep_mop"), ("B", "sweep")])])
        assert "mopped" in activity["A"]
        assert "mopped" not in activity["B"]

    def test_keeps_latest_per_kind(self):
        tasks = [
            _rooms_task([("R", "sweep_mop")], start=1_000_000, task_id="a"),
            _rooms_task([("R", "sweep")], start=9_000_000, task_id="b"),
        ]
        entry = room_activity(tasks)["R"]
        assert entry["vacuumed"] == 9_660_000
        assert entry["mopped"] == 1_660_000

    def test_zone_is_assigned_by_centre(self):
        shape = SimpleNamespace(id="ROOM_1", polygon=[(0, 0), (4, 0), (4, 4), (0, 4)])
        task = {
            "action": "clean_areas",
            "timestamp": 0,
            "duration": 100_000,
            "cleanTime": 90_000,
            "actionParam": {
                "areas": [{"mode": {"type": "sweep"}, "polygon": [[1, 1], [2, 1], [2, 2], [1, 2]]}],
            },
        }
        assert task_rooms(task, [shape]) == [("ROOM_1", "sweep")]
        assert task_rooms(task, []) == []

    def test_clean_all_covers_every_known_room(self):
        task = {
            "action": "clean_all",
            "timestamp": 0,
            "duration": 100_000,
            "cleanTime": 90_000,
            "actionParam": {"mode": {"type": "sweep"}},
        }
        assert set(room_activity([task], known_rooms=["A", "B"])) == {"A", "B"}


class TestSummary:
    def test_uses_newest_cleaning_run_and_room_names(self):
        tasks = [
            _rooms_task([("R1", "sweep")], start=1_000, task_id="old"),
            _rooms_task([("R2", "sweep_mop")], start=9_000_000, task_id="new"),
            _rooms_task([("R3", "sweep")], start=99_000_000, clean=0, task_id="aborted"),
        ]
        summary = last_task_summary(tasks, rooms={"R2": "Küche"})
        assert summary["rooms"] == ["Küche"]
        assert summary["vacuumed"] and summary["mopped"]
        assert summary["clean_minutes"] == 10.0

    def test_none_without_cleaning_runs(self):
        assert last_task_summary([]) is None


class TestStore:
    def test_compact_drops_account_identifiers(self):
        assert "userID" not in compact_record(_rooms_task([("R", "sweep")]))

    def test_merge_reports_changes_only_when_new(self):
        record = _rooms_task([("R", "sweep")])
        merged, changed = merge_records({}, [record])
        assert changed
        merged, changed = merge_records(merged, [record])
        assert not changed

    def test_merge_caps_and_keeps_newest(self):
        records = [
            _rooms_task([("R", "sweep")], start=i, task_id=f"t{i}")
            for i in range(MAX_STORED_TASKS + 5)
        ]
        merged, _ = merge_records({}, records)
        assert len(merged) == MAX_STORED_TASKS
        assert "t0" not in merged
