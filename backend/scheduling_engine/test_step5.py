"""Checks for Step 5 on made-up data. Run from backend:  python -m scheduling_engine.test_step5"""
import random
from dataclasses import replace
from datetime import datetime, timedelta

from .models import Assignment, ChosenBlock
from .step2_feasibility import merge, occupancy
from .step5_validate import DbRequest, DbTrain, check_schedule, train_interval
from .test_steps_1_2 import D, H, T, T18237, T_B

TRAINS = [DbTrain(t.train_id, True, None, None, set(t.running_days),
                  [(s.chainage, s.arrival, s.departure) for s in t.stops]) for t in (T18237, T_B)]


def rq(bid, dept, lo, hi, start=T(14), dur=H(1), direction="DOWN"):
    return DbRequest(bid, dept, direction, lo, hi, start, dur)


def base():
    """A valid little schedule: a and b share block 1, c has block 2."""
    reqs = {"a": rq("a", "S&T", 20, 22), "b": rq("b", "S&T", 21, 23), "c": rq("c", "Engineering", 40, 41)}
    blocks = [ChosenBlock(1, 1, 2, 20, 23, T(14), T(15), ("a", "b")),
              ChosenBlock(2, 2, 2, 40, 41, T(14), T(15), ("c",))]
    assigns = [Assignment("a", 1, T(14), T(15), 0), Assignment("b", 1, T(14), T(15), 0),
               Assignment("c", 2, T(14), T(15), 0)]
    return reqs, blocks, assigns


def run(reqs, blocks, assigns, unassigned=(), rejected=()):
    return check_schedule(D, reqs, TRAINS, blocks, assigns, list(unassigned), list(rejected))


def has(problems, text):
    return any(text in p for p in problems)


def test_valid_schedule_passes():
    assert run(*base()) == []


def test_every_request_exactly_once():
    reqs, blocks, assigns = base()
    assert has(run(reqs, blocks, assigns[:2]), "c: has 0 outcomes")                  # c vanished
    assert run(reqs, blocks[:1], assigns[:2], unassigned=["c"]) == []                 # c not granted
    assert run(reqs, blocks[:1], assigns[:2], rejected=["c"]) == []                   # c rejected earlier
    assert has(run(reqs, blocks, assigns, unassigned=["c"]), "c: has 2 outcomes")     # granted and not granted
    assert has(run(reqs, blocks, assigns + [assigns[0]]), "a: has 2 outcomes")        # granted twice
    assert has(run(reqs, blocks, assigns, rejected=["zzz"]), "zzz")                   # unknown request


def test_duration_and_timing_of_slots():
    reqs, blocks, assigns = base()
    short = [replace(assigns[0], end=T(14, 30))] + assigns[1:]
    assert has(run(reqs, blocks, short), "request needs")
    early = [replace(assigns[0], start=T(13, 55), end=T(14, 55), delay_minutes=-5)] + assigns[1:]
    assert has(run(reqs, blocks, early), "before the preferred start")
    late_blocks = [replace(blocks[0], start=T(16, 5), end=T(17, 5))] + blocks[1:]
    late = [replace(assigns[0], start=T(16, 5), end=T(17, 5), delay_minutes=125)] + assigns[1:]
    assert has(run(reqs, late_blocks, late), "after the preferred start")
    exactly_two_hours = [replace(assigns[0], start=T(16), end=T(17), delay_minutes=120)] + assigns[1:]
    ok_blocks = [replace(blocks[0], start=T(14), end=T(17))] + blocks[1:]
    assert not has(run(reqs, ok_blocks, exactly_two_hours), "after the preferred start")
    outside = [replace(assigns[0], start=T(15), end=T(16), delay_minutes=60)] + assigns[1:]
    assert has(run(reqs, blocks, outside), "is not inside block")
    wrong_delay = [replace(assigns[0], delay_minutes=7)] + assigns[1:]
    assert has(run(reqs, blocks, wrong_delay), "recorded delay")


def test_stretch_must_be_covered_and_line_must_match():
    reqs, blocks, assigns = base()
    assert has(run(reqs, [replace(blocks[0], lo=21)] + blocks[1:], assigns), "not covered")
    assert has(run(reqs, [replace(blocks[0], hi=22.5)] + blocks[1:], assigns), "not covered")
    assert has(run(reqs, [replace(blocks[0], line=1)] + blocks[1:], assigns), "does not match")
    # an Up request is on line 1, which is switched off for now
    up = {"u": rq("u", "S&T", 20, 21, direction="UP")}
    ub = [ChosenBlock(1, 1, 1, 20, 21, T(14), T(15), ("u",))]
    ua = [Assignment("u", 1, T(14), T(15), 0)]
    assert has(run(up, ub, ua), "switched off")


def test_cap_compatibility_and_length_rules():
    reqs, blocks, assigns = base()
    # four requests in one block
    reqs4 = {k: rq(k, "S&T", 20, 22) for k in "abcd"}
    b4 = [ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), tuple("abcd"))]
    a4 = [Assignment(k, 1, T(14), T(15), 0) for k in "abcd"]
    assert has(run(reqs4, b4, a4), "serves 4 requests")
    # S&T and Engineering overlapping on km
    mixed = {"a": rq("a", "S&T", 20, 22), "e": rq("e", "Engineering", 21, 23)}
    bm = [ChosenBlock(1, 1, 2, 20, 23, T(14), T(15), ("a", "e"))]
    am = [Assignment("a", 1, T(14), T(15), 0), Assignment("e", 1, T(14), T(15), 0)]
    assert has(run(mixed, bm, am), "overlap on km but may not share")
    # the same two at different km are fine
    apart = {"a": rq("a", "S&T", 20, 21), "e": rq("e", "Engineering", 22, 23)}
    assert run(apart, [ChosenBlock(1, 1, 2, 20, 23, T(14), T(15), ("a", "e"))], am) == []
    # touching at one point counts as overlapping
    touch = {"a": rq("a", "S&T", 20, 21), "e": rq("e", "Elec", 21, 22)}
    assert has(run(touch, [ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), ("a", "e"))], am), "overlap on km")
    # Elec with Elec may overlap ("Elect" spelling too)
    ee = {"a": rq("a", "Elec", 20, 22), "e": rq("e", "Elect", 21, 23)}
    assert run(ee, [ChosenBlock(1, 1, 2, 20, 23, T(14), T(15), ("a", "e"))], am) == []
    # two Civil/Engineering requests may not overlap
    cc = {"a": rq("a", "Civil", 20, 22), "e": rq("e", "Engineering", 21, 23)}
    assert has(run(cc, [ChosenBlock(1, 1, 2, 20, 23, T(14), T(15), ("a", "e"))], am), "may not share")
    # combined stretch above 15 km
    far = {"a": rq("a", "S&T", 20, 21), "e": rq("e", "S&T", 40, 41)}
    assert has(run(far, [ChosenBlock(1, 1, 2, 20, 41, T(14), T(15), ("a", "e"))], am), "combined stretch")


def test_block_must_stay_inside_the_day():
    reqs, blocks, assigns = base()
    late = [replace(blocks[0], start=T(23, 30), end=T(23, 30) + H(1))] + blocks[1:]
    la = [replace(assigns[0], start=T(23, 30), end=T(23, 30) + H(1), delay_minutes=570),
          replace(assigns[1], start=T(23, 30), end=T(23, 30) + H(1), delay_minutes=570)] + assigns[2:]
    assert has(run(reqs, late, la), "is not inside")


def test_trains_with_margin():
    # 18237 is in Barara-Mustafabad (139-148 km) 00:50-00:59, so 00:45-01:04 with margin; T_B 00:58-01:17
    reqs = {"x": rq("x", "S&T", 139, 148, T(0, 0), H(0, 40))}
    def sched(start, end):
        return ([ChosenBlock(1, 1, 2, 139, 148, start, end, ("x",))],
                [Assignment("x", 1, start, end, int((start - T(0, 0)).total_seconds() // 60))])
    ok_b, ok_a = sched(T(0, 0), T(0, 40))                       # ends 00:40, 5 minutes before the margin starts
    assert run(reqs, ok_b, ok_a) == []
    b, a = sched(T(0, 5), T(0, 45))                             # ends exactly when the margin starts: fine
    assert run(reqs, b, a) == []
    b, a = sched(T(0, 10), T(0, 50))                            # inside the margin
    assert has(run(reqs, b, a), "clashes with train 18237")
    b, a = sched(T(1, 17), T(1, 57))                            # starts exactly when the last margin ends
    assert run(reqs, b, a) == []
    b, a = sched(T(1, 10), T(1, 50))
    assert has(run(reqs, b, a), "clashes with train T_B")


def test_blocks_may_not_overlap():
    reqs, blocks, assigns = base()
    two = {"a": rq("a", "S&T", 20, 22), "b": rq("b", "Engineering", 21, 23)}
    b = [ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), ("a",)), ChosenBlock(2, 2, 2, 21, 23, T(14, 30), T(15, 30), ("b",))]
    a = [Assignment("a", 1, T(14), T(15), 0), Assignment("b", 2, T(14, 30), T(15, 30), 30)]
    assert has(run(two, b, a), "overlap on the same line")
    b = [ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), ("a",)), ChosenBlock(2, 2, 2, 21, 23, T(15), T(16), ("b",))]
    a = [Assignment("a", 1, T(14), T(15), 0), Assignment("b", 2, T(15), T(16), 60)]
    assert not has(run(two, b, a), "overlap on the same line")           # back to back is allowed


def test_train_method_agrees_with_step_2_method():
    """Step 5 works out entry and exit times; Step 2 adds up segments. They must agree."""
    rng = random.Random(3)
    for t in (T18237, T_B):
        db = next(x for x in TRAINS if x.train_id == t.train_id)
        base_dt = datetime(2026, 10, 21)
        for _ in range(300):
            lo = round(rng.uniform(0, 194), 2)
            hi = round(lo + rng.uniform(0.05, 25), 2)
            spans = merge(occupancy(t, lo, hi, base_dt))
            iv = train_interval(db.stops, lo, hi)
            if not spans:
                assert iv is None, (t.train_id, lo, hi)
            else:
                assert iv is not None, (t.train_id, lo, hi)
                assert (base_dt + iv[0], base_dt + iv[1]) == (spans[0][0], spans[-1][1]), (t.train_id, lo, hi)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
