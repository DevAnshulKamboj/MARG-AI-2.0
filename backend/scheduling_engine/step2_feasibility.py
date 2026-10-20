"""Step 2 - which requests can fit between trains?

Each request is checked on its own. For its stretch and line we build the busy
intervals (every train on that line, 5 minutes clear before and after, plus
blocks already granted) and try start times from the preferred start up to
2 hours later. A start is feasible if the full duration fits without touching
a busy interval. A request with no feasible start is rejected here for good:
merging requests in Step 3 can only make a stretch bigger, never easier.

How a train occupies a stretch
  * Between two timetable rows its position is interpolated by chainage.
  * Dwelling at a station inside the stretch occupies it from arrival to departure.
  * Every train is assumed to stay on the SRE-LDH line from its first row to its last.
    If a timetable has no row for a station it passes, its position there is still
    interpolated along the line, so a missing PASS row can never free a block.
Times are offsets from 00:00 of the service day; 24:00 and above means the next day.
A train runs on service day S if S's ISO weekday (Mon=1 ... Sun=7) is in running_days.
Trains of day D-1 that run past midnight are included.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from .config import MAX_START_DELAY, SAFETY_MARGIN, START_STEP
from .models import FeasibleRequest, GrantedBlock, Rejection, Request, Stop, Train

Interval = tuple[datetime, datetime]


@dataclass
class TrainData:
    trains: list[Train]


# ---------------------------------------------------------------- database ----

def load_train_data(conn) -> TrainData:
    trains: dict[str, Train] = {}
    for r in conn.execute(text(
        "SELECT train_id, train_name, priority, is_active, valid_from, valid_to FROM trains.trains"
    )).mappings():
        trains[r["train_id"]] = Train(
            train_id=r["train_id"], name=r["train_name"], priority=r["priority"],
            is_active=r["is_active"], valid_from=r["valid_from"], valid_to=r["valid_to"],
            running_days=set(),
        )

    for train_id, weekday in conn.execute(text("SELECT train_id, weekday FROM trains.running_days")):
        if train_id in trains:
            trains[train_id].running_days.add(int(weekday))

    for r in conn.execute(text(
        """
        SELECT ts.train_id, ts.stop_seq, ts.station_id, s.chainage_km,
               ts.stop_type, ts.arrival, ts.departure
        FROM   trains.timetable_stops ts
        JOIN   infra.stations s ON s.station_id = ts.station_id
        ORDER  BY ts.train_id, ts.stop_seq
        """
    )).mappings():
        if r["train_id"] in trains:
            trains[r["train_id"]].stops.append(Stop(
                seq=r["stop_seq"], station_id=r["station_id"], chainage=float(r["chainage_km"]),
                stop_type=r["stop_type"], arrival=r["arrival"], departure=r["departure"],
            ))
    return TrainData(list(trains.values()))


# ---------------------------------------------------------- train occupancy ----

def train_runs_on(train: Train, service_day: date) -> bool:
    if not train.is_active:
        return False
    if train.valid_from is not None and service_day < train.valid_from:
        return False
    if train.valid_to is not None and service_day > train.valid_to:
        return False
    return service_day.isoweekday() in train.running_days


def _leave_time(stop: Stop) -> timedelta | None:
    return stop.departure if stop.departure is not None else stop.arrival


def _reach_time(stop: Stop) -> timedelta | None:
    return stop.arrival if stop.arrival is not None else stop.departure


def _time_at(c: float, ca: float, cb: float, ta: timedelta, tb: timedelta) -> timedelta:
    if ca == cb:
        return ta
    return ta + (tb - ta) * ((c - ca) / (cb - ca))


def occupancy(train: Train, lo: float, hi: float, base: datetime) -> list[Interval]:
    """Times (no margin yet) when `train` is inside chainage [lo, hi]. `base` = 00:00 of its service day."""
    out: list[Interval] = []
    stops = train.stops

    # dwelling at a station inside the stretch
    for s in stops:
        if lo <= s.chainage <= hi:
            t0, t1 = _reach_time(s), _leave_time(s)
            if t0 is None or t1 is None:
                continue
            out.append((base + min(t0, t1), base + max(t0, t1)))

    # running between consecutive rows
    for a, b in zip(stops, stops[1:]):
        seg_lo, seg_hi = min(a.chainage, b.chainage), max(a.chainage, b.chainage)
        if seg_hi < lo or seg_lo > hi:
            continue
        ta, tb = _leave_time(a), _reach_time(b)
        if ta is None or tb is None:
            continue
        if tb < ta:
            raise ValueError(f"Train {train.train_id}: time goes backwards between "
                             f"stop_seq {a.seq} and {b.seq}")
        c1, c2 = max(lo, seg_lo), min(hi, seg_hi)
        t1 = _time_at(c1, a.chainage, b.chainage, ta, tb)
        t2 = _time_at(c2, a.chainage, b.chainage, ta, tb)
        out.append((base + min(t1, t2), base + max(t1, t2)))
    return out


def merge(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping or touching intervals."""
    merged: list[Interval] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def busy_intervals(data: TrainData, block_date: date, lo: float, hi: float, direction: str,
                   granted: list[GrantedBlock] | tuple = (), line: int | None = None,
                   margin: timedelta = SAFETY_MARGIN) -> list[Interval]:
    """Merged busy intervals for a stretch: trains with margins, plus granted blocks."""
    day_start = datetime.combine(block_date, time.min)
    day_end = day_start + timedelta(days=1)
    spans: list[Interval] = []
    for train in data.trains:
        if train.direction != direction:
            continue
        for service_day in (block_date - timedelta(days=1), block_date):
            if not train_runs_on(train, service_day):
                continue
            base = datetime.combine(service_day, time.min)
            for s, e in occupancy(train, lo, hi, base):
                if e + margin <= day_start or s - margin >= day_end:
                    continue                      # nowhere near the block date
                spans.append((s - margin, e + margin))
    for g in granted:
        if line is not None and g.line == line and g.lo < hi and g.hi > lo:
            spans.append((g.start, g.end))
    return merge(spans)


# ------------------------------------------------------------ feasibility ----

def feasible_starts(req: Request, busy: list[Interval], day_end: datetime) -> list[datetime]:
    latest = min(req.preferred_start + MAX_START_DELAY, day_end - req.duration)
    starts: list[datetime] = []
    s = req.preferred_start
    while s <= latest:
        e = s + req.duration
        if not any(s < b_end and e > b_start for b_start, b_end in busy):
            starts.append(s)
        s += START_STEP
    return starts


def run_step2(requests: list[Request], data: TrainData, block_date: date,
              granted: list[GrantedBlock] | tuple = ()
              ) -> tuple[list[FeasibleRequest], list[Rejection]]:
    day_end = datetime.combine(block_date + timedelta(days=1), time.min)
    feasible: list[FeasibleRequest] = []
    rejected: list[Rejection] = []

    for req in requests:
        if req.preferred_start + req.duration > day_end:
            rejected.append(Rejection(req.block_id, 2,
                            "block cannot finish before the end of the day"))
            continue
        busy = busy_intervals(data, block_date, req.lo, req.hi, req.direction,
                              granted, req.line)
        starts = feasible_starts(req, busy, day_end)
        if starts:
            feasible.append(FeasibleRequest(req, busy, starts))
        else:
            rejected.append(Rejection(req.block_id, 2,
                            "no train-free window of the needed length within the 2-hour delay limit"))
    return feasible, rejected
