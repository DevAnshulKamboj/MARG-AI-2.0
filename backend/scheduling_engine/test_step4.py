"""Checks for Step 4. Run from backend:  python -m scheduling_engine.test_step4

Most checks need only plain Python. The checks that call the CP-SAT solver need OR-Tools and
are skipped (and say so) if it is not installed. On your machine all of them run: the solver
is compared against a plain-Python exhaustive search on small cases.
"""
import itertools
import random
from datetime import datetime, timedelta

from . import step2_feasibility
from .models import Candidate, Request
from .step2_feasibility import run_step2
from .step3_candidates import run_step3
from .step4_optimize import (Option, build_options, coefficients, conflict_pairs, conflicting,
                             objective_weights, run_step4, solve_cpsat, solve_reference)
from .test_steps_1_2 import D, DATA, H, T

try:
    import ortools  # noqa: F401
    HAVE_ORTOOLS = True
except ImportError:
    HAVE_ORTOOLS = False


def mk(bid, dept, lo, hi, start, dur=H(1), score=0.5):
    return Request(bid, dept, "test", None, "DOWN", 2, lo, hi, start, None, dur, score, 1)


def pipeline(reqs, narrow=True):
    """Steps 2 and 3, optionally with a short 15-minute delay window to keep cases small."""
    saved = step2_feasibility.MAX_START_DELAY
    if narrow:
        step2_feasibility.MAX_START_DELAY = timedelta(minutes=15)
    try:
        feasible, rejected = run_step2(reqs, DATA, D)
    finally:
        step2_feasibility.MAX_START_DELAY = saved
    res = run_step3(feasible, DATA, D)
    return feasible, res.candidates


def opt(i, ids, score, minutes, delay, line=2, lo=0.0, hi=1.0, start=T(14), end=None):
    end = end or start + timedelta(minutes=minutes)
    c = Candidate(i + 1, line, lo, hi, start, end, tuple(ids))
    return Option(i, c, tuple(ids), score, minutes, {r: delay // len(ids) for r in ids}, {})


def tuple_value(options, chosen):
    return (sum(options[i].score for i in chosen), -sum(options[i].minutes for i in chosen),
            -len(chosen), -sum(options[i].delay for i in chosen))


def valid(options, pairs, chosen):
    clash = set(pairs)
    used = [r for i in chosen for r in options[i].request_ids]
    if len(used) != len(set(used)):
        return False
    return not any((i, j) in clash or (j, i) in clash for i, j in itertools.combinations(chosen, 2))


# ------------------------------------------------------------ pure Python ----

def test_weights_keep_the_goals_in_strict_order():
    rng = random.Random(7)
    for _ in range(300):
        n_req = rng.randint(1, 4)
        reqs = [f"r{k}" for k in range(n_req)]
        options = []
        for i in range(rng.randint(2, 8)):
            ids = rng.sample(reqs, rng.randint(1, min(2, n_req)))
            options.append(opt(i, ids, rng.randint(0, 3) * 100 + rng.randint(0, 1) * 50,
                               rng.randint(1, 6) * 15, rng.randint(0, 40) * len(ids)))
        pairs = [(i, j) for i, j in itertools.combinations(range(len(options)), 2) if rng.random() < 0.25]
        coefs = coefficients(options)
        best_w, best_t = None, None
        for r in range(len(options) + 1):
            for chosen in itertools.combinations(range(len(options)), r):
                if not valid(options, pairs, chosen):
                    continue
                w = sum(coefs[i] for i in chosen)
                t = tuple_value(options, chosen)
                if best_w is None or w > best_w:
                    best_w = w
                if best_t is None or t > best_t:
                    best_t = t
        # the selection with the best weighted value must have the best lexicographic value
        top = max((c for r in range(len(options) + 1) for c in itertools.combinations(range(len(options)), r)
                   if valid(options, pairs, c)), key=lambda c: sum(coefs[i] for i in c))
        assert tuple_value(options, top) == best_t


def test_reference_prefers_higher_score_over_everything_else():
    # a and b clash. b scores more but is longer and later: it still wins.
    options = [opt(0, ["a"], 400, 30, 0), opt(1, ["b"], 500, 120, 90)]
    assert solve_reference(options, [(0, 1)]) == [1]


def test_reference_then_fewer_block_minutes_then_fewer_blocks_then_less_delay():
    # same score: shorter total block time wins
    options = [opt(0, ["a"], 500, 60, 0), opt(1, ["a"], 500, 30, 50)]
    assert solve_reference(options, []) == [1]
    # same score and minutes: fewer blocks wins (one block for a+b beats two blocks)
    options = [opt(0, ["a", "b"], 1000, 60, 0), opt(1, ["a"], 500, 30, 0), opt(2, ["b"], 500, 30, 0)]
    assert solve_reference(options, []) == [0]
    # same everything else: smaller delay wins
    options = [opt(0, ["a"], 500, 60, 40), opt(1, ["a"], 500, 60, 10)]
    assert solve_reference(options, []) == [1]


def test_reference_never_grants_a_request_twice_or_breaks_a_clash():
    options = [opt(0, ["a", "b"], 900, 60, 0), opt(1, ["b", "c"], 900, 60, 0), opt(2, ["c"], 400, 30, 0)]
    chosen = solve_reference(options, [])
    assert valid(options, [], chosen)
    assert tuple_value(options, chosen)[0] == 1300      # a+b with c alone beats b+c with nothing for a


def test_conflict_rule():
    base = dict(line=2, lo=10.0, hi=12.0, start=T(14), end=T(15), request_ids=("x",))
    a = Candidate(1, **base)
    assert conflicting(a, Candidate(2, **{**base, "lo": 12.0, "hi": 13.0}))                 # touch at 12 km
    assert not conflicting(a, Candidate(3, **{**base, "lo": 12.5, "hi": 13.0}))             # km apart
    assert not conflicting(a, Candidate(4, **{**base, "start": T(15), "end": T(16)}))       # back to back
    assert conflicting(a, Candidate(5, **{**base, "start": T(14, 59), "end": T(16)}))
    assert not conflicting(a, Candidate(6, **{**base, "line": 1}))


def test_options_have_the_earliest_slot_and_correct_totals():
    reqs = [mk("a", "S&T", 20, 22, T(14), score=0.6), mk("b", "S&T", 21, 23, T(14, 30), score=0.4)]
    feasible, cands = pipeline(reqs, narrow=False)
    options = build_options(feasible, cands)
    shared = [o for o in options if len(o.request_ids) == 2 and (o.candidate.start, o.candidate.end) == (T(14, 30), T(15, 30))]
    assert len(shared) == 1
    o = shared[0]
    assert o.score == 1000 and o.minutes == 60
    assert o.slots["a"] == (T(14, 30), T(15, 30)) and o.slots["b"] == (T(14, 30), T(15, 30))
    assert o.delays == {"a": 30, "b": 0}


def test_reference_on_real_pipeline_shares_a_block_when_it_can():
    # a and b overlap on km and are both S&T, so one shared block (60 min) beats two sequential blocks (120 min)
    reqs = [mk("a", "S&T", 20, 22, T(14)), mk("b", "S&T", 21, 23, T(14, 15))]
    feasible, cands = pipeline(reqs)
    options = build_options(feasible, cands)
    chosen = solve_reference(options, conflict_pairs(options))
    assert len(chosen) == 1 and set(options[chosen[0]].request_ids) == {"a", "b"}


def test_reference_separates_departments_that_overlap_on_km():
    # S&T and Engineering overlap on km so they cannot share. Their possible times overlap, but the
    # blocks may not coincide, so they are placed one after the other (both fit).
    reqs = [mk("a", "S&T", 20, 22, T(14), H(0, 30)), mk("b", "Engineering", 21, 23, T(14, 30), H(0, 30))]
    feasible, cands = pipeline(reqs)
    options = build_options(feasible, cands)
    chosen = solve_reference(options, conflict_pairs(options))
    assert len(chosen) == 2 and all(len(options[i].request_ids) == 1 for i in chosen)
    c1, c2 = (options[i].candidate for i in chosen)
    assert not conflicting(c1, c2)


# ----------------------------------------------------------------- CP-SAT ----

def test_cpsat_matches_reference_on_small_cases():
    if not HAVE_ORTOOLS:
        print("      (skipped: OR-Tools not installed here)")
        return
    cases = [
        [mk("a", "S&T", 20, 22, T(14)), mk("b", "S&T", 21, 23, T(14, 15))],
        [mk("a", "S&T", 20, 22, T(14), H(0, 30)), mk("b", "Engineering", 21, 23, T(14), H(0, 30)),
         mk("c", "Elec", 30, 31, T(14), H(0, 30))],
        [mk("a", "Elec", 20, 22, T(14), score=0.9), mk("b", "Elec", 20, 22, T(14), score=0.2),
         mk("c", "Engineering", 21, 25, T(14, 10), H(2), score=0.5), mk("d", "S&T", 40, 41, T(14))],
    ]
    for reqs in cases:
        feasible, cands = pipeline(reqs)
        options = build_options(feasible, cands)
        pairs = conflict_pairs(options)
        _, got = solve_cpsat(options, pairs)
        want = solve_reference(options, pairs)
        assert valid(options, pairs, got)
        assert tuple_value(options, got) == tuple_value(options, want), (got, want)


def test_run_step4_end_to_end_and_empty():
    empty = run_step4([], [])
    assert empty.n_blocks == 0 and empty.unassigned == []
    if not HAVE_ORTOOLS:
        print("      (skipped: OR-Tools not installed here)")
        return
    feasible, cands = pipeline([mk("a", "S&T", 20, 22, T(14)), mk("b", "S&T", 21, 23, T(14, 15))])
    res = run_step4(feasible, cands)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert res.n_blocks == 1 and res.unassigned == []
    assert {a.block_id for a in res.assignments} == {"a", "b"}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed" + ("" if HAVE_ORTOOLS else " (solver checks skipped)"))
