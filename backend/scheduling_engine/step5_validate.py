"""Step 5 - independent validation of the solver's result.

Nothing here uses the solver or the code of Steps 2 to 4. The requests and the train
timetables are read from the database again, and every rule is re-checked from scratch.
Trains are tested with a different method from Step 2: instead of adding up segments, it
works out when each train enters and leaves the block's stretch.

Checks
  1. every request of the day has exactly one outcome (granted, not granted or rejected);
  2. each granted request: full duration inside its block, no early start, no start more
     than 2 hours late, block stretch covers the request's stretch, block is on the
     request's line, and that line is switched on;
  3. each block: starts and ends on the block date, 1 to 3 requests, combined stretch within
     the length limit, and every pair of its requests passes the department rule;
  4. no train in any block's stretch, time or 5-minute margin;
  5. no two blocks overlap on the same line, km range and time.

If anything fails, ValidationFailed is raised with every problem found. The caller must then
stop the run and save nothing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import combinations

from sqlalchemy import text

from .config import (DEPARTMENT_GROUPS, DIRECTION_TO_LINE, ENABLED_LINES, MAX_BLOCK_LENGTH_KM,
                     MAX_REQUESTS_PER_BLOCK, MAX_START_DELAY, SAFETY_MARGIN, SAME_KM_OK_GROUPS)

EPS = 1e-9


class ValidationFailed(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__(f"{len(violations)} validation problem(s)")


@dataclass
class DbRequest:
    block_id: str
    dept: str | None
    direction: str
    lo: float
    hi: float
    preferred_start: datetime
    duration: timedelta


@dataclass
class DbTrain:
    train_id: str
    is_active: bool
    valid_from: object
    valid_to: object
    running_days: set
    stops: list            # (chainage, arrival, departure) in timetable order


@dataclass
class Step5Result:
    passed: bool
    blocks_checked: int
    assignments_checked: int
    trains_checked: int


# ---------------------------------------------------------------- database ----

def load_requests(conn, block_date: date) -> dict[str, DbRequest]:
    rows = conn.execute(text(
        """
        SELECT block_id, dept, direction, location_from, location_to, demanded_from, duration
        FROM   block_requests
        WHERE  demanded_from >= :d0 AND demanded_from < :d1
        """), {"d0": block_date, "d1": block_date + timedelta(days=1)}).mappings()
    out = {}
    for r in rows:
        a, b = r["location_from"], r["location_to"]
        lo, hi = (None, None) if a is None or b is None else (min(float(a), float(b)), max(float(a), float(b)))
        out[r["block_id"]] = DbRequest(r["block_id"], r["dept"], (r["direction"] or "").strip().upper(),
                                       lo, hi, r["demanded_from"], r["duration"])
    return out


def load_trains(conn) -> list[DbTrain]:
    trains: dict[str, DbTrain] = {}
    for r in conn.execute(text(
            "SELECT train_id, is_active, valid_from, valid_to FROM trains.trains")).mappings():
        trains[r["train_id"]] = DbTrain(r["train_id"], r["is_active"], r["valid_from"], r["valid_to"], set(), [])
    for train_id, weekday in conn.execute(text("SELECT train_id, weekday FROM trains.running_days")):
        if train_id in trains:
            trains[train_id].running_days.add(int(weekday))
    for r in conn.execute(text(
            """
            SELECT ts.train_id, s.chainage_km, ts.arrival, ts.departure
            FROM   trains.timetable_stops ts
            JOIN   infra.stations s ON s.station_id = ts.station_id
            ORDER  BY ts.train_id, ts.stop_seq
            """)).mappings():
        if r["train_id"] in trains:
            trains[r["train_id"]].stops.append((float(r["chainage_km"]), r["arrival"], r["departure"]))
    return list(trains.values())


# ------------------------------------------------------------ train method ----

def time_range_at(stops: list, c: float):
    """(first, last) time the train is at chainage c, or None if it never is."""
    for ch, arr, dep in stops:
        if abs(ch - c) < EPS:
            t0 = arr if arr is not None else dep
            t1 = dep if dep is not None else arr
            if t0 is None:
                return None
            return min(t0, t1), max(t0, t1)
    for (c1, a1, d1), (c2, a2, d2) in zip(stops, stops[1:]):
        if min(c1, c2) < c < max(c1, c2):
            ta = d1 if d1 is not None else a1
            tb = a2 if a2 is not None else d2
            t = ta + (tb - ta) * ((c - c1) / (c2 - c1))
            return t, t
    return None


def train_interval(stops: list, lo: float, hi: float):
    """(entry, exit) offsets when the train is inside [lo, hi], or None if it never is."""
    chs = [s[0] for s in stops]
    cmin, cmax = min(chs), max(chs)
    if cmax < lo or cmin > hi:
        return None
    if stops[0][0] > stops[-1][0]:           # chainage falls: the train moves from high to low
        c_in, c_out = min(hi, cmax), max(lo, cmin)
    else:
        c_in, c_out = max(lo, cmin), min(hi, cmax)
    a, b = time_range_at(stops, c_in), time_range_at(stops, c_out)
    if a is None or b is None:
        return None
    return a[0], b[1]


def _train_direction(stops: list) -> str | None:
    if len(stops) < 2 or abs(stops[0][0] - stops[-1][0]) < EPS:
        return None
    return "UP" if stops[-1][0] > stops[0][0] else "DOWN"


def _runs_on(t: DbTrain, day: date) -> bool:
    if not t.is_active:
        return False
    if t.valid_from is not None and day < t.valid_from:
        return False
    if t.valid_to is not None and day > t.valid_to:
        return False
    return day.isoweekday() in t.running_days


# ------------------------------------------------------------------ checks ----

def _group(dept) -> str:
    key = (dept or "").strip().upper()
    return DEPARTMENT_GROUPS.get(key, key or "UNKNOWN")


def check_schedule(block_date: date, requests: dict, trains: list, blocks: list, assignments: list,
                   unassigned: list, rejected_ids: list) -> list[str]:
    v: list[str] = []
    day_start = datetime.combine(block_date, time.min)
    day_end = day_start + timedelta(days=1)

    # 1. every request has exactly one outcome
    outcomes = defaultdict(list)
    for a in assignments:
        outcomes[a.block_id].append("granted")
    for rid in unassigned:
        outcomes[rid].append("not granted")
    for rid in rejected_ids:
        outcomes[rid].append("rejected")
    for rid in requests:
        if len(outcomes[rid]) != 1:
            v.append(f"{rid}: has {len(outcomes[rid])} outcomes {outcomes[rid]}, expected exactly one")
    for rid in outcomes:
        if rid not in requests:
            v.append(f"{rid}: has an outcome but is not a request for {block_date}")

    # block numbers must be unique
    by_no = {}
    for b in blocks:
        if b.block_no in by_no:
            v.append(f"block number {b.block_no} is used twice")
        by_no[b.block_no] = b

    # 2. each granted request
    members = defaultdict(list)
    for a in assignments:
        b = by_no.get(a.block_no)
        r = requests.get(a.block_id)
        if b is None:
            v.append(f"{a.block_id}: assigned to block {a.block_no}, which does not exist")
            continue
        members[a.block_no].append(a.block_id)
        if r is None:
            continue
        if r.lo is None or r.hi is None:
            v.append(f"{a.block_id}: granted but has no stretch")
            continue
        if a.end - a.start != r.duration:
            v.append(f"{a.block_id}: slot is {a.end - a.start}, request needs {r.duration}")
        if a.start < r.preferred_start:
            v.append(f"{a.block_id}: starts {r.preferred_start - a.start} before the preferred start")
        if a.start - r.preferred_start > MAX_START_DELAY:
            v.append(f"{a.block_id}: starts {a.start - r.preferred_start} after the preferred start "
                     f"(limit {MAX_START_DELAY})")
        if a.start < b.start or a.end > b.end:
            v.append(f"{a.block_id}: slot {a.start:%H:%M}-{a.end:%H:%M} is not inside block {b.block_no} "
                     f"({b.start:%H:%M}-{b.end:%H:%M})")
        if b.lo > r.lo + EPS or b.hi < r.hi - EPS:
            v.append(f"{a.block_id}: request stretch {r.lo:g}-{r.hi:g} km is not covered by block "
                     f"{b.block_no} ({b.lo:g}-{b.hi:g} km)")
        line = DIRECTION_TO_LINE.get(r.direction)
        if line is None or b.line != line:
            v.append(f"{a.block_id}: direction {r.direction} does not match block {b.block_no} on line {b.line}")
        if line is not None and line not in ENABLED_LINES:
            v.append(f"{a.block_id}: line {line} is switched off")
        want = int((a.start - r.preferred_start).total_seconds() // 60)
        if a.delay_minutes != want:
            v.append(f"{a.block_id}: recorded delay {a.delay_minutes} min, real delay {want} min")

    # 3. each block
    for b in blocks:
        ids = members.get(b.block_no, [])
        if set(ids) != set(b.request_ids):
            v.append(f"block {b.block_no}: lists {sorted(b.request_ids)} but serves {sorted(ids)}")
        if not 1 <= len(ids) <= MAX_REQUESTS_PER_BLOCK:
            v.append(f"block {b.block_no}: serves {len(ids)} requests (allowed 1 to {MAX_REQUESTS_PER_BLOCK})")
        if not b.start < b.end:
            v.append(f"block {b.block_no}: ends before it starts")
        if b.start < day_start or b.end > day_end:
            v.append(f"block {b.block_no}: {b.start:%d %b %H:%M}-{b.end:%d %b %H:%M} is not inside {block_date}")
        reqs = [requests[i] for i in ids if i in requests and requests[i].lo is not None]
        if len(reqs) > 1:
            span = max(r.hi for r in reqs) - min(r.lo for r in reqs)
            if span > MAX_BLOCK_LENGTH_KM + EPS:
                v.append(f"block {b.block_no}: combined stretch {span:g} km is above {MAX_BLOCK_LENGTH_KM:g} km")
        for r1, r2 in combinations(reqs, 2):
            if r1.lo <= r2.hi and r2.lo <= r1.hi:                     # overlap on km (touching counts)
                g1, g2 = _group(r1.dept), _group(r2.dept)
                if not (g1 == g2 and g1 in SAME_KM_OK_GROUPS):
                    v.append(f"block {b.block_no}: {r1.block_id} ({r1.dept}) and {r2.block_id} ({r2.dept}) "
                             f"overlap on km but may not share")

    # 4. no train in any block's stretch, time or margin
    for b in blocks:
        for t in trains:
            if not t.stops or _train_direction(t.stops) is None:
                continue
            if DIRECTION_TO_LINE.get(_train_direction(t.stops)) != b.line:
                continue
            for service_day in (block_date - timedelta(days=1), block_date):
                if not _runs_on(t, service_day):
                    continue
                iv = train_interval(t.stops, b.lo, b.hi)
                if iv is None:
                    continue
                base = datetime.combine(service_day, time.min)
                t_in, t_out = base + iv[0] - SAFETY_MARGIN, base + iv[1] + SAFETY_MARGIN
                if b.start < t_out and b.end > t_in:
                    v.append(f"block {b.block_no} ({b.lo:g}-{b.hi:g} km, {b.start:%H:%M}-{b.end:%H:%M}) clashes "
                             f"with train {t.train_id} ({t_in:%H:%M}-{t_out:%H:%M} incl. margin)")

    # 5. no two blocks overlap on the same line, km range and time
    for b1, b2 in combinations(blocks, 2):
        if (b1.line == b2.line and b1.lo <= b2.hi and b2.lo <= b1.hi
                and b1.start < b2.end and b2.start < b1.end):
            v.append(f"blocks {b1.block_no} and {b2.block_no} overlap on the same line, km range and time")
    return v


def run_step5(conn, block_date: date, step4, rejected: list) -> Step5Result:
    """`step4` is the Step 4 result; `rejected` is the Step 1 and Step 2 rejections together."""
    requests = load_requests(conn, block_date)
    trains = load_trains(conn)
    problems = check_schedule(block_date, requests, trains, step4.blocks, step4.assignments,
                              step4.unassigned, [r.block_id for r in rejected])
    if problems:
        raise ValidationFailed(problems)
    return Step5Result(True, len(step4.blocks), len(step4.assignments), len(trains))
