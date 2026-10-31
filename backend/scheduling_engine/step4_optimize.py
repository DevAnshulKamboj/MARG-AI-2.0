"""Step 4 - choose which candidate blocks become real blocks (OR-Tools CP-SAT).

Model
  One yes/no choice per candidate from Step 3. A chosen candidate serves ALL the requests
  listed in it, each working in its earliest possible slot inside the block, so the slot
  (and its delay) is fixed for every candidate. Smaller groups exist as their own
  candidates, so nothing is lost by choosing whole candidates.

Hard rules
  * each request is granted at most once;
  * two chosen blocks may not overlap on the same line, km range and time
    (km ranges that only touch at one point count as overlapping; blocks may run back to back);
  * the work slot has the requested duration, starts no earlier than preferred and at most
    2 hours later, and lies inside its block; no train is in the block's stretch and time,
    and the compatibility rules and the per-block cap hold. All of these are already built
    into the candidates by Steps 2 and 3, and Step 5 re-checks them independently.

Objective, in strict order of importance
  (a) maximize the total rounded priority score granted;
  (b) minimize total block minutes;
  (c) minimize the number of blocks;
  (d) minimize total delay from the preferred starts.
  The four goals are combined into one number with weights chosen so that a gain in an
  earlier goal always beats any possible gain in all the later goals together.

An empty schedule is always possible, so a solver result of "nothing found" is a bug and
raises an error instead of returning quietly.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .config import (SCORE_SCALE, SOLVER_TIME_LIMIT_SECONDS, SOLVER_WORKERS)
from .models import (Assignment, Candidate, ChosenBlock, FeasibleRequest, Step4Result)


@dataclass(frozen=True)
class Option:
    """A candidate with everything the solver needs, precomputed."""
    index: int
    candidate: Candidate
    request_ids: tuple[str, ...]
    score: int                                  # sum of members' rounded scores
    minutes: int                                # block length
    delays: dict                                # request id -> delay in minutes (read only)
    slots: dict                                 # request id -> (start, end)

    @property
    def delay(self) -> int:
        return sum(self.delays.values())


# ------------------------------------------------------------- preparation ----

def round_score(score: float) -> int:
    return int(round(score * SCORE_SCALE))


def _minutes(delta) -> int:
    return int(delta.total_seconds() // 60)


def slot_for(fr: FeasibleRequest, cand: Candidate) -> tuple[datetime, datetime]:
    """Earliest possible work slot of this request inside this block."""
    d = fr.request.duration
    for s in fr.starts:
        if s >= cand.start and s + d <= cand.end:
            return s, s + d
    raise ValueError(f"Candidate {cand.candidate_id} has no slot for {fr.request.block_id}")


def build_options(feasible: list[FeasibleRequest], candidates: list[Candidate]) -> list[Option]:
    by_id = {f.request.block_id: f for f in feasible}
    options: list[Option] = []
    for i, c in enumerate(candidates):
        slots, delays, score = {}, {}, 0
        for rid in c.request_ids:
            fr = by_id[rid]
            start, end = slot_for(fr, c)
            slots[rid] = (start, end)
            delays[rid] = _minutes(start - fr.request.preferred_start)
            score += round_score(fr.request.score)
        options.append(Option(i, c, c.request_ids, score, _minutes(c.end - c.start), delays, slots))
    return options


def conflicting(a: Candidate, b: Candidate) -> bool:
    """Same line, km ranges overlap (touching counts), and times overlap."""
    return (a.line == b.line
            and a.lo <= b.hi and b.lo <= a.hi
            and a.start < b.end and b.start < a.end)


def conflict_pairs(options: list[Option]) -> list[tuple[int, int]]:
    out = []
    for i in range(len(options)):
        ci = options[i].candidate
        for j in range(i + 1, len(options)):
            if conflicting(ci, options[j].candidate):
                out.append((i, j))
    return out


def objective_weights(options: list[Option]) -> tuple[int, int, int, int]:
    """(w_score, w_minutes, w_blocks, w_delay) so that the goals are strictly ordered."""
    max_delay: dict[str, int] = defaultdict(int)
    max_minutes: dict[str, int] = defaultdict(int)
    for o in options:
        for rid in o.request_ids:
            max_delay[rid] = max(max_delay[rid], o.delays[rid])
            max_minutes[rid] = max(max_minutes[rid], o.minutes)
    delay_bound = sum(max_delay.values())          # no selection can have more total delay
    minutes_bound = sum(max_minutes.values())      # nor more total block minutes
    blocks_bound = len(max_delay)                  # nor more blocks than requests
    w_delay = 1
    w_blocks = delay_bound + 1
    w_minutes = blocks_bound * w_blocks + delay_bound + 1
    w_score = minutes_bound * w_minutes + blocks_bound * w_blocks + delay_bound + 1
    return w_score, w_minutes, w_blocks, w_delay


def coefficients(options: list[Option]) -> list[int]:
    ws, wm, wb, wd = objective_weights(options)
    return [ws * o.score - wm * o.minutes - wb - wd * o.delay for o in options]


# ----------------------------------------------------------------- solvers ----

def solve_cpsat(options: list[Option], pairs: list[tuple[int, int]]) -> tuple[str, list[int]]:
    from ortools.sat.python import cp_model

    def call(obj, snake, camel, *args):
        fn = getattr(obj, snake, None) or getattr(obj, camel)
        return fn(*args)

    model = cp_model.CpModel()
    x = [call(model, "new_bool_var", "NewBoolVar", f"x{o.index}") for o in options]

    by_request: dict[str, list[int]] = defaultdict(list)
    for o in options:
        for rid in o.request_ids:
            by_request[rid].append(o.index)
    for rid, idx in by_request.items():
        if len(idx) > 1:
            call(model, "add_at_most_one", "AddAtMostOne", [x[i] for i in idx])
    for i, j in pairs:
        call(model, "add_at_most_one", "AddAtMostOne", [x[i], x[j]])

    coefs = coefficients(options)
    call(model, "maximize", "Maximize", sum(c * v for c, v in zip(coefs, x)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    solver.parameters.random_seed = 1
    try:
        solver.parameters.num_workers = SOLVER_WORKERS
    except AttributeError:
        solver.parameters.num_search_workers = SOLVER_WORKERS

    status = call(solver, "solve", "Solve", model)
    name = call(solver, "status_name", "StatusName", status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        raise RuntimeError(f"Solver returned {name}. An empty schedule is always possible, "
                           f"so this is a bug in the model. Stop and check the candidates.")
    chosen = [o.index for o, v in zip(options, x) if call(solver, "boolean_value", "BooleanValue", v)]
    return name, chosen


def solve_reference(options: list[Option], pairs: list[tuple[int, int]]) -> list[int]:
    """Plain-Python exhaustive search with the same rules and the same goal order.
    Only for small cases: it exists to cross-check the CP-SAT model in tests."""
    clash: dict[int, set[int]] = defaultdict(set)
    for i, j in pairs:
        clash[i].add(j)
        clash[j].add(i)
    by_request: dict[str, list[int]] = defaultdict(list)
    for o in options:
        for rid in o.request_ids:
            by_request[rid].append(o.index)
    order = sorted(by_request)
    best: list = [None, []]

    def value(chosen):
        return (sum(options[i].score for i in chosen), -sum(options[i].minutes for i in chosen),
                -len(chosen), -sum(options[i].delay for i in chosen))

    def dfs(k, chosen, used):
        if k == len(order):
            v = value(chosen)
            if best[0] is None or v > best[0]:
                best[0], best[1] = v, list(chosen)
            return
        rid = order[k]
        dfs(k + 1, chosen, used)                       # leave this request without a block
        if rid in used:
            return
        for i in by_request[rid]:
            if any(m in used for m in options[i].request_ids):
                continue
            if any(j in clash[i] for j in chosen):
                continue
            chosen.append(i)
            dfs(k + 1, chosen, used | set(options[i].request_ids))
            chosen.pop()

    dfs(0, [], frozenset())
    return best[1]


# ------------------------------------------------------------------ result ----

def make_result(status: str, options: list[Option], chosen: list[int],
                feasible: list[FeasibleRequest], seconds: float) -> Step4Result:
    picked = sorted((options[i] for i in chosen),
                    key=lambda o: (o.candidate.start, o.candidate.lo, o.candidate.candidate_id))
    blocks, assignments, granted = [], [], set()
    for n, o in enumerate(picked, start=1):
        c = o.candidate
        blocks.append(ChosenBlock(n, c.candidate_id, c.line, c.lo, c.hi, c.start, c.end, c.request_ids))
        for rid in c.request_ids:
            s, e = o.slots[rid]
            assignments.append(Assignment(rid, n, s, e, o.delays[rid]))
            granted.add(rid)
    unassigned = sorted(f.request.block_id for f in feasible if f.request.block_id not in granted)
    return Step4Result(
        status=status, blocks=blocks, assignments=assignments, unassigned=unassigned,
        total_score=sum(o.score for o in picked),
        total_block_minutes=sum(o.minutes for o in picked),
        n_blocks=len(picked),
        total_delay_minutes=sum(o.delay for o in picked),
        seconds=seconds,
    )


def run_step4(feasible: list[FeasibleRequest], candidates: list[Candidate]) -> Step4Result:
    t0 = time.time()
    if not candidates:
        return make_result("OPTIMAL", [], [], feasible, 0.0)
    options = build_options(feasible, candidates)
    pairs = conflict_pairs(options)
    status, chosen = solve_cpsat(options, pairs)
    return make_result(status, options, chosen, feasible, time.time() - t0)
