"""Checks for Step 3 on made-up data. Run from backend:  python -m scheduling_engine.test_step3"""
from datetime import timedelta

from .models import Request
from .step2_feasibility import run_step2
from .step3_candidates import run_step3
from .test_steps_1_2 import D, DATA, H, T


def mk(bid, dept, lo, hi, start, dur=H(1)):
    return Request(bid, dept, "test", None, "DOWN", 2, lo, hi, start, None, dur, 0.5, 1)


def build(reqs):
    feasible, rejected = run_step2(reqs, DATA, D)
    assert not rejected, rejected
    return feasible, run_step3(feasible, DATA, D)


def shared(res, *ids):
    return [c for c in res.candidates if set(c.request_ids) == set(ids)]


def test_every_request_has_standalone_candidates():
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "Elec", 80, 81, T(14))])
    for f in feasible:
        singles = [c for c in res.candidates if c.request_ids == (f.request.block_id,)]
        assert len(singles) == len(f.starts) == 25
    assert res.n_shared == 0          # 59 km apart: longer than the 15 km limit


def test_st_with_st_may_overlap_and_share():
    feasible, res = build([mk("a", "S&T", 20, 22, T(14)), mk("b", "S&T", 21, 23, T(14, 30))])
    c = shared(res, "a", "b")
    assert c and all((x.lo, x.hi) == (20, 23) for x in c)      # combined stretch
    # simultaneous work 14:30-15:30 is the shortest option
    assert any((x.start, x.end) == (T(14, 30), T(15, 30)) for x in c)


def test_different_departments_cannot_overlap_on_km():
    feasible, res = build([mk("a", "S&T", 20, 22, T(14)), mk("b", "Engineering", 21, 23, T(14))])
    assert shared(res, "a", "b") == []


def test_different_departments_can_share_when_km_apart():
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "Engineering", 22, 23, T(14))])
    c = shared(res, "a", "b")
    assert c and all((x.lo, x.hi) == (20, 23) for x in c)


def test_touching_ranges_count_as_overlap():
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "Elec", 21, 22, T(14))])
    assert shared(res, "a", "b") == []


def test_civil_is_engineering_and_two_eng_cannot_overlap():
    feasible, res = build([mk("a", "Civil", 20, 22, T(14)), mk("b", "Engineering", 21, 23, T(14))])
    assert shared(res, "a", "b") == []
    feasible, res = build([mk("a", "Civil", 20, 21, T(14)), mk("b", "Engineering", 22, 23, T(14))])
    assert shared(res, "a", "b")


def test_elec_with_elec_may_overlap():
    feasible, res = build([mk("a", "Elec", 20, 22, T(14)), mk("b", "Elec", 20, 22, T(14))])
    assert shared(res, "a", "b")


def test_block_length_limit():
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "S&T", 36.5, 37, T(14))])   # 17 km hull
    assert shared(res, "a", "b") == []
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "S&T", 34, 35, T(14))])      # exactly 15 km
    assert shared(res, "a", "b")


def test_time_windows_must_overlap():
    # a may start 14:00-16:00 (works until 17:00); b may start 19:00-21:00
    feasible, res = build([mk("a", "S&T", 20, 21, T(14)), mk("b", "S&T", 20, 21, T(19))])
    assert shared(res, "a", "b") == []


def test_at_most_three_requests_per_block():
    reqs = [mk(x, "S&T", 20, 21, T(14)) for x in "abcd"]
    feasible, res = build(reqs)
    assert max(len(c.request_ids) for c in res.candidates) == 3
    assert shared(res, "a", "b", "c", "d") == []
    assert shared(res, "a", "b", "c") and shared(res, "b", "c", "d")


def test_candidates_touching_a_train_are_discarded():
    # Barara-Mustafabad (139-148) is busy 00:45-01:17. Request a is clear (starts 02:00+);
    # request b may start 00:00-02:00, but only its later starts are feasible on its own.
    a = mk("a", "S&T", 139, 140, T(2), H(0, 30))
    b = mk("b", "S&T", 141, 142, T(0, 0), H(0, 30))
    feasible, res = build([a, b])
    assert shared(res, "a", "b")                      # later, train-free options survive
    for c in shared(res, "a", "b"):
        assert not (c.start < T(1, 17) and c.end > T(0, 45)), (c.start, c.end)
    # the single candidates of b that avoid the train are kept
    assert any(c.request_ids == ("b",) and c.start == T(0, 0) for c in res.candidates)


def test_candidate_ids_are_unique_and_sequential():
    feasible, res = build([mk("a", "S&T", 20, 22, T(14)), mk("b", "S&T", 21, 23, T(14, 30))])
    assert [c.candidate_id for c in res.candidates] == list(range(1, len(res.candidates) + 1))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
