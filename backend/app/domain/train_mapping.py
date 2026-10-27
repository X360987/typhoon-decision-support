"""Map suspensions to province-hour using timetable stops.

The full run of a train instance is placed on an absolute timeline first (origin
departure date + cumulative midnight crossings), and only then clipped to the
suspended segment. Unmatched endpoints or ambiguous timetable versions are sent
to review instead of defaulting to the whole route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable


@dataclass
class Stop:
    train_code: str
    stop_order: int
    station_name: str
    province_code: str
    arrive_time: str | None
    depart_time: str | None
    timetable_version: str = "default"
    valid_from: datetime | None = None
    valid_to: datetime | None = None


@dataclass
class SuspensionInput:
    suspension_id: int
    train_code: str
    suspension_date: datetime
    segment_start: str | None
    segment_end: str | None
    timetable_version: str | None = None


@dataclass
class RegionHourHit:
    suspension_id: int
    province_code: str
    hour_bj: datetime
    train_code: str
    estimate_basis: str
    run_key: str = ""
    stations: list[str] = field(default_factory=list)


@dataclass
class MappingResult:
    status: str  # mapped | pending_review | no_timetable
    reason: str | None
    hits: list[RegionHourHit]
    run_key: str
    timetable_version: str | None


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _hour_on_date(base_date: datetime, hhmm: str | None, day_offset: int = 0) -> datetime | None:
    parsed = _parse_hhmm(hhmm)
    if not parsed:
        return None
    h, m = parsed
    d = (base_date + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    return d + timedelta(hours=h, minutes=m)


def select_timetable(
    stops: list[Stop], run_date: datetime, requested_version: str | None
) -> tuple[list[Stop] | None, str | None, str | None]:
    """Return (stops of one version, version, reason when unresolved)."""
    versions: dict[str, list[Stop]] = {}
    for s in stops:
        versions.setdefault(s.timetable_version, []).append(s)
    if not versions:
        return None, None, "no_timetable"
    if requested_version:
        if requested_version in versions:
            return versions[requested_version], requested_version, None
        return None, None, "timetable_version_not_found"
    if len(versions) == 1:
        version = next(iter(versions))
        return versions[version], version, None
    day = run_date.replace(hour=0, minute=0, second=0, microsecond=0)
    valid = []
    for v, vs in versions.items():
        lo = min((s.valid_from for s in vs if s.valid_from), default=None)
        hi = max((s.valid_to for s in vs if s.valid_to), default=None)
        if (lo is None or lo <= day) and (hi is None or day <= hi) and (lo is not None or hi is not None):
            valid.append(v)
    if len(valid) == 1:
        return versions[valid[0]], valid[0], None
    return None, None, "timetable_version_ambiguous"


def build_run_timeline(stops: list[Stop], run_date: datetime) -> list[tuple[Stop, datetime]]:
    """Absolute time of each stop for the instance departing its origin on ``run_date``."""
    ordered = sorted(stops, key=lambda s: s.stop_order)
    timeline: list[tuple[Stop, datetime]] = []
    day_offset = 0
    prev: int | None = None
    for stop in ordered:
        t = stop.depart_time or stop.arrive_time
        parsed = _parse_hhmm(t)
        if not parsed:
            continue
        minutes = parsed[0] * 60 + parsed[1]
        if prev is not None and minutes < prev:
            day_offset += 1
        prev = minutes
        when = _hour_on_date(run_date, t, day_offset)
        if when is not None:
            timeline.append((stop, when))
    return timeline


def map_suspension(suspension: SuspensionInput, stops: Iterable[Stop]) -> MappingResult:
    own = [s for s in stops if s.train_code == suspension.train_code]
    run_date = suspension.suspension_date.replace(hour=0, minute=0, second=0, microsecond=0)
    run_key = f"{suspension.train_code}|{run_date.date().isoformat()}"
    if not own:
        return MappingResult("no_timetable", "no_timetable", [], run_key, None)
    chosen, version, reason = select_timetable(own, run_date, suspension.timetable_version)
    if chosen is None:
        return MappingResult("pending_review", reason, [], run_key, None)

    timeline = build_run_timeline(chosen, run_date)
    names = [s.station_name for s, _ in timeline]
    start_idx, end_idx = 0, len(timeline) - 1
    if suspension.segment_start:
        if suspension.segment_start not in names:
            return MappingResult("pending_review", "segment_start_unmatched", [], run_key, version)
        start_idx = names.index(suspension.segment_start)
    if suspension.segment_end:
        if suspension.segment_end not in names:
            return MappingResult("pending_review", "segment_end_unmatched", [], run_key, version)
        end_idx = names.index(suspension.segment_end)
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    basis = "timetable_segment_hour" if (suspension.segment_start or suspension.segment_end) else "timetable_full_run"

    grouped: dict[tuple[str, datetime], list[str]] = {}
    for stop, when in timeline[start_idx : end_idx + 1]:
        key = (stop.province_code, when.replace(minute=0, second=0, microsecond=0))
        grouped.setdefault(key, []).append(stop.station_name)
    hits = [
        RegionHourHit(
            suspension_id=suspension.suspension_id,
            province_code=prov,
            hour_bj=hour,
            train_code=suspension.train_code,
            estimate_basis=basis,
            run_key=run_key,
            stations=stations,
        )
        for (prov, hour), stations in grouped.items()
    ]
    return MappingResult("mapped", None, hits, run_key, version)


def map_suspension_to_region_hours(suspension: SuspensionInput, stops: Iterable[Stop]) -> list[RegionHourHit]:
    return map_suspension(suspension, stops).hits
