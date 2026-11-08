"""Evaluate the cloud's cleaning task records. Deliberately free of Home Assistant imports.

A record comes from ``/sweeper/v1/taskRecord/list``. The relevant parts are ``timestamp``
(start, ms), ``duration`` and ``cleanTime`` (ms), ``taskArea`` (m²), ``action``,
``result`` and ``actionParam``, which holds the rooms or areas with their cleaning mode.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Shorter runs were aborted before cleaning anything meaningful.
MIN_CLEAN_MS = 60_000
MAX_STORED_TASKS = 500

CLEANING_ACTIONS = frozenset({"clean_all", "clean_rooms", "clean_areas", "clean_here"})
VACUUM_TYPES = frozenset({"sweep", "sweep_mop", "first_sweep_then_mop"})
MOP_TYPES = frozenset({"mop", "sweep_mop", "first_sweep_then_mop"})

_STORED_KEYS = (
    "taskID", "timestamp", "duration", "cleanTime", "taskArea",
    "action", "actionParam", "result", "source",
)


def compact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the fields we use, dropping account identifiers."""
    return {key: record.get(key) for key in _STORED_KEYS}


def merge_records(
    stored: Mapping[str, dict[str, Any]],
    fetched: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Merge fetched records into the store, returning the result and whether it changed."""
    merged = dict(stored)
    changed = False
    for record in fetched:
        task_id = record.get("taskID")
        if not task_id:
            continue
        compact = compact_record(record)
        if merged.get(task_id) != compact:
            merged[task_id] = compact
            changed = True
    if len(merged) > MAX_STORED_TASKS:
        newest = sorted(merged.values(), key=_start_ms, reverse=True)[:MAX_STORED_TASKS]
        merged = {task["taskID"]: task for task in newest}
    return merged, changed


def _start_ms(task: Mapping[str, Any]) -> int:
    return int(task.get("timestamp") or 0)


def end_ms(task: Mapping[str, Any]) -> int:
    """Return when the task finished, in ms since the epoch."""
    return _start_ms(task) + int(task.get("duration") or 0)


def is_cleaning_task(task: Mapping[str, Any]) -> bool:
    """Return True for a run that really cleaned, even if it was stopped early."""
    return (
        task.get("action") in CLEANING_ACTIONS
        and int(task.get("cleanTime") or 0) >= MIN_CLEAN_MS
    )


def _mode_type(entry: Mapping[str, Any] | None) -> str | None:
    mode = entry.get("mode") if isinstance(entry, Mapping) else None
    return mode.get("type") if isinstance(mode, Mapping) else None


def _center(polygon: list[list[float]]) -> tuple[float, float] | None:
    points = [p for p in polygon if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not points:
        return None
    return (
        sum(float(p[0]) for p in points) / len(points),
        sum(float(p[1]) for p in points) / len(points),
    )


def _inside(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray casting point-in-polygon test."""
    x, y = point
    inside = False
    for i, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(i + 1) % len(polygon)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def task_rooms(
    task: Mapping[str, Any],
    room_shapes: Iterable[Any] = (),
    known_rooms: Iterable[str] = (),
) -> list[tuple[str, str]]:
    """Return ``(room_id, mode_type)`` for every room the task covered.

    Zones (``clean_areas``) count for the room containing their centre, and only if the
    map is available. ``clean_all`` counts for every known room.
    """
    param = task.get("actionParam")
    if not isinstance(param, Mapping):
        return []

    result: list[tuple[str, str]] = []
    for room in param.get("rooms") or []:
        room_id = room.get("room_id") if isinstance(room, Mapping) else None
        mode_type = _mode_type(room)
        if room_id and mode_type:
            result.append((room_id, mode_type))

    shapes = list(room_shapes)
    for area in param.get("areas") or []:
        if not isinstance(area, Mapping):
            continue
        mode_type = _mode_type(area)
        center = _center(area.get("polygon") or [])
        if not mode_type or center is None:
            continue
        for shape in shapes:
            if _inside(center, shape.polygon):
                result.append((shape.id, mode_type))
                break

    if task.get("action") == "clean_all" and not result:
        mode_type = _mode_type(param)
        if mode_type:
            result.extend((room_id, mode_type) for room_id in known_rooms)

    return result


def room_activity(
    tasks: Iterable[Mapping[str, Any]],
    room_shapes: Iterable[Any] = (),
    known_rooms: Iterable[str] = (),
) -> dict[str, dict[str, int]]:
    """Return, per room, when it was last vacuumed and last mopped (end time in ms)."""
    shapes = list(room_shapes)
    rooms = list(known_rooms)
    activity: dict[str, dict[str, int]] = {}
    for task in tasks:
        if not is_cleaning_task(task):
            continue
        finished = end_ms(task)
        for room_id, mode_type in task_rooms(task, shapes, rooms):
            entry = activity.setdefault(room_id, {})
            if mode_type in VACUUM_TYPES:
                entry["vacuumed"] = max(entry.get("vacuumed", 0), finished)
            if mode_type in MOP_TYPES:
                entry["mopped"] = max(entry.get("mopped", 0), finished)
    return activity


def last_task_summary(
    tasks: Iterable[Mapping[str, Any]],
    room_shapes: Iterable[Any] = (),
    rooms: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Describe the most recent run that really cleaned."""
    cleaning = [task for task in tasks if is_cleaning_task(task)]
    if not cleaning:
        return None
    task = max(cleaning, key=_start_ms)
    names = rooms or {}
    covered = task_rooms(task, room_shapes, names)
    return {
        "start_ms": _start_ms(task),
        "end_ms": end_ms(task),
        "rooms": [names.get(room_id, room_id) for room_id, _ in covered],
        "room_ids": [room_id for room_id, _ in covered],
        "vacuumed": any(mode in VACUUM_TYPES for _, mode in covered),
        "mopped": any(mode in MOP_TYPES for _, mode in covered),
        "clean_minutes": round(int(task.get("cleanTime") or 0) / 60000, 1),
        "area": task.get("taskArea"),
        "action": task.get("action"),
        "result": task.get("result"),
        "source": task.get("source"),
    }
