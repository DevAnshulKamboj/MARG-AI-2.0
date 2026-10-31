"""Step 3 - build the menu of possible blocks for the solver (Step 4) to choose from.

Every candidate is a stretch on a line, a start, an end and the requests it could serve.

Stand-alone candidates
  Every feasible request gets one candidate per possible start time: its own stretch,
  from that start to start + duration. Nothing is ever lost here.

Shared candidates (2 to MAX_REQUESTS_PER_BLOCK requests)
  Requests may share a block only if ALL of these hold for every pair:
    * same line;
    * their possible start windows overlap in time;
    * the combined stretch is at most MAX_BLOCK_LENGTH_KM long;
    * the department rule: S&T with S&T, or ELEC with ELEC, may work on overlapping km;
      any other pair must not overlap on km (touching at one point counts as overlapping).
  The block's stretch is the combined stretch of its requests. Its time runs from the
  earliest work start to the latest work end. For each possible block start, every request
  takes its earliest possible start at or after it, which keeps the block as short as it can be.

Every candidate is then checked against the busy times of its combined stretch (trains with
their 5-minute margins, and blocks already granted). A candidate that touches a busy time
is discarded.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations

from .config import (DEPARTMENT_GROUPS, MAX_BLOCK_LENGTH_KM, MAX_REQUESTS_PER_BLOCK,
                     SAME_KM_OK_GROUPS)
from .models import Candidate, FeasibleRequest, GrantedBlock
from .step2_feasibility import TrainData, busy_intervals


@dataclass
class Step3Result:
    candidates: list[Candidate]
    n_single: int
    n_shared: int
    groups_tried: int                 # request groups that passed the pair rules
    groups_blocked_by_trains: int     # groups that passed the pair rules but had no train-free slot


# ----------------------------------------------------------------- rules ----

def department_group(dept: str | None) -> str:
    key = (dept or "").strip().upper()
    return DEPARTMENT_GROUPS.get(key, key or "UNKNOWN")


def km_overlap(a: FeasibleRequest, b: FeasibleRequest) -> bool:
    """Closed ranges: touching at one km point counts as overlapping."""
    return a.request.lo <= b.request.hi and b.request.lo <= a.request.hi


def start_window(f: FeasibleRequest) -> tuple[datetime, datetime]:
    return f.starts[0], f.starts[-1] + f.request.duration


def pair_allowed(a: FeasibleRequest, b: FeasibleRequest) -> bool:
    ra, rb = a.request, b.request
    if ra.line != rb.line:
        return False
    (a0, a1), (b0, b1) = start_window(a), start_window(b)
    if not (a0 < b1 and b0 < a1):                       # possible times must overlap
        return False
    if max(ra.hi, rb.hi) - min(ra.lo, rb.lo) > MAX_BLOCK_LENGTH_KM:
        return False
    if km_overlap(a, b):
        ga, gb = department_group(ra.dept), department_group(rb.dept)
        if not (ga == gb and ga in SAME_KM_OK_GROUPS):
            return False
    return True


# ------------------------------------------------------------ generation ----

def _fits(start: datetime, end: datetime, busy) -> bool:
    return not any(start < b_end and end > b_start for b_start, b_end in busy)


def shared_intervals(members: list[FeasibleRequest]) -> list[tuple[datetime, datetime]]:
    """Compact (start, end) options for a block serving all members."""
    all_starts = sorted({s for m in members for s in m.starts})
    seen: set[tuple[datetime, datetime]] = set()
    out: list[tuple[datetime, datetime]] = []
    for bs in all_starts:
        slots = []
        for m in members:
            i = bisect_left(m.starts, bs)
            if i == len(m.starts):
                break
            s = m.starts[i]
            slots.append((s, s + m.request.duration))
        else:
            iv = (min(s for s, _ in slots), max(e for _, e in slots))
            if iv not in seen:
                seen.add(iv)
                out.append(iv)
    return out


def run_step3(feasible: list[FeasibleRequest], data: TrainData, block_date: date,
              granted: list[GrantedBlock] | tuple = ()) -> Step3Result:
    raw: list[tuple] = []     # (line, lo, hi, start, end, ids)

    # stand-alone candidates: one per possible start of every feasible request
    for f in feasible:
        r = f.request
        for s in f.starts:
            raw.append((r.line, r.lo, r.hi, s, s + r.duration, (r.block_id,)))
    n_single = len(raw)

    # shared candidates
    groups_tried = groups_blocked = 0
    ordered = sorted(feasible, key=lambda f: f.request.block_id)
    allowed = {(a.request.block_id, b.request.block_id): pair_allowed(a, b)
               for a, b in combinations(ordered, 2)}

    for size in range(2, MAX_REQUESTS_PER_BLOCK + 1):
        for members in combinations(ordered, size):
            ids = [m.request.block_id for m in members]
            if not all(allowed[(x, y)] for x, y in combinations(ids, 2)):
                continue
            lo = min(m.request.lo for m in members)
            hi = max(m.request.hi for m in members)
            if hi - lo > MAX_BLOCK_LENGTH_KM:
                continue
            groups_tried += 1
            line = members[0].request.line
            direction = members[0].request.direction
            busy = busy_intervals(data, block_date, lo, hi, direction, granted, line)
            kept = [(s, e) for s, e in shared_intervals(list(members)) if _fits(s, e, busy)]
            if not kept:
                groups_blocked += 1
            for s, e in kept:
                raw.append((line, lo, hi, s, e, tuple(ids)))

    candidates = [Candidate(i + 1, *row) for i, row in enumerate(raw)]
    return Step3Result(candidates, n_single, len(candidates) - n_single, groups_tried, groups_blocked)
