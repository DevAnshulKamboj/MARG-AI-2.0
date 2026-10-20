"""Checks for Steps 1 and 2 on made-up data. Run from backend:  python -m scheduling_engine.test_steps_1_2"""
from datetime import date, datetime, timedelta

from .models import Request, Stop, Train
from .step1_load_requests import validate_requests
from .step2_feasibility import TrainData, busy_intervals, run_step2

D = date(2026, 10, 21)            # a Wednesday
H = lambda h, m=0: timedelta(hours=h, minutes=m)
T = lambda h, m=0: datetime(2026, 10, 21, h, m)

# chainage km from Ludhiana (approximate, test only)
CH = {"LDH": 0, "SAN": 15.086, "CHA": 31.673, "KHA": 42.628, "GOV": 50.733, "SIR": 60.391,
      "SAD": 68.15, "SAR": 76.266, "RAJ": 85.734, "AMC": 105.978, "ACJ": 113.455,
      "DUK": 121, "KES": 127, "TAN": 133, "BAR": 139, "MUS": 148, "DAR": 155,
      "JWS": 160, "YJ": 165, "KAL": 171, "SRS": 182, "PIL": 187, "SRE": 195}
SID = {code: i + 1 for i, code in enumerate(CH)}


def train(tid, rows, days=(1, 2, 3, 4, 5, 6, 7)):
    stops = [Stop(i + 1, SID[c], float(CH[c]), typ, arr, dep)
             for i, (c, typ, arr, dep) in enumerate(rows)]
    return Train(tid, tid, 3, True, None, None, set(days), stops)


# 18237: SRE -> LDH, the whole main line (rows as loaded in the database)
T18237 = train("18237", [
    ("SRE", "STOP", H(0, 0), H(0, 5)), ("PIL", "PASS", H(0, 11), H(0, 11)),
    ("SRS", "PASS", H(0, 16), H(0, 16)), ("KAL", "PASS", H(0, 26), H(0, 26)),
    ("YJ", "STOP", H(0, 32), H(0, 34)), ("JWS", "STOP", H(0, 39), H(0, 41)),
    ("DAR", "PASS", H(0, 44), H(0, 44)), ("MUS", "PASS", H(0, 50), H(0, 50)),
    ("BAR", "STOP", H(0, 57), H(0, 59)), ("TAN", "PASS", H(1, 6), H(1, 6)),
    ("KES", "PASS", H(1, 15), H(1, 15)), ("DUK", "PASS", H(1, 24), H(1, 24)),
    ("ACJ", "STOP", H(1, 35), H(1, 40)), ("AMC", "STOP", H(1, 50), H(1, 52)),
    ("RAJ", "STOP", H(2, 5), H(2, 7)), ("SAR", "PASS", H(2, 14), H(2, 14)),
    ("SAD", "PASS", H(2, 20), H(2, 20)), ("SIR", "STOP", H(2, 26), H(2, 28)),
    ("GOV", "STOP", H(2, 34), H(2, 36)), ("KHA", "STOP", H(2, 43), H(2, 45)),
    ("CHA", "PASS", H(2, 56), H(2, 56)), ("SAN", "PASS", H(3, 15), H(3, 15)),
    ("LDH", "STOP", H(3, 33), H(3, 43)),
])
# a second Down train, straight through the line (rows only where the test needs them)
T_B = train("T_B", [
    ("SRE", "STOP", H(0, 15), H(0, 20)), ("MUS", "PASS", H(1, 3), H(1, 3)),
    ("BAR", "PASS", H(1, 12), H(1, 12)), ("LDH", "STOP", H(4, 36), H(4, 46)),
])
DATA = TrainData([T18237, T_B])


def req(bid, direction, lo, hi, start, dur):
    return Request(bid, "ENG", "test", None, direction, 1 if direction == "UP" else 2,
                   lo, hi, start, None, dur, 0.5, 1)


# ------------------------------------------------------------------ Step 1 ----
def test_step1_validation():
    base = dict(dept="ENG", reason="x", sub_section="s", demanded_to=None,
                topsis_score=0.7, rank=1, duration=H(1), demanded_from=T(10),
                direction="down", location_from=50, location_to=40)
    rows = [
        {**base, "block_id": "ok"},                                   # reversed locations, lower-case direction
        {**base, "block_id": "same", "location_to": 50},
        {**base, "block_id": "far", "location_from": 3265.002, "location_to": 522.225},
        {**base, "block_id": "nodur", "duration": timedelta(0)},
        {**base, "block_id": "wrongday", "demanded_from": datetime(2026, 10, 22, 10)},
        {**base, "block_id": "noscore", "topsis_score": None},
        {**base, "block_id": "baddir", "direction": "sideways"},
    ]
    valid, rejected = validate_requests(rows, D, 0.0, 195.0)
    assert [r.block_id for r in valid] == ["ok"]
    assert (valid[0].lo, valid[0].hi, valid[0].line, valid[0].direction) == (40, 50, 2, "DOWN")
    assert {r.block_id for r in rejected} == {"same", "far", "nodur", "wrongday", "noscore", "baddir"}


# ------------------------------------------------------------------ Step 2 ----
def test_down_block_avoids_trains_with_margin():
    # Barara (139) - Mustafabad (148), Down line.
    # 18237 is there 00:50-00:59 -> busy 00:45-01:04; T_B is there 01:03-01:12 -> 00:58-01:17.
    busy = busy_intervals(DATA, D, 139, 148, "DOWN")
    assert busy == [(T(0, 45), T(1, 17))]


def test_up_line_has_no_down_trains():
    assert busy_intervals(DATA, D, 139, 148, "UP") == []


def test_missing_pass_rows_still_block():
    # only two rows: SRE (195 km) leaves 00:00, LDH (0 km) arrives 03:15 -> 1 minute per km, nothing in between
    sparse = train("SPARSE", [("SRE", "STOP", H(0, 0), H(0, 0)), ("LDH", "STOP", H(3, 15), H(3, 15))])
    busy = busy_intervals(TrainData([sparse]), D, 100, 110, "DOWN")
    # at 110 km the train is there at 01:25, at 100 km at 01:35, plus 5 minutes each side
    assert busy == [(T(1, 20), T(1, 40))]


def test_feasible_starts():
    # 10-minute Down block at Barara-Mustafabad, preferred 00:30
    r = req("a", "DOWN", 139, 148, T(0, 30), H(0, 10))
    feasible, rejected = run_step2([r], DATA, D)
    assert not rejected
    starts = feasible[0].starts
    assert starts[0] == T(0, 30) and T(0, 35) in starts      # ends 00:45, exactly at the margin
    assert T(0, 40) not in starts and T(1, 15) not in starts
    assert T(1, 20) in starts and starts[-1] == T(2, 30)      # first start after 01:17, 2-hour limit


def test_rejected_when_no_window():
    # a train halts at Barara 01:20-03:20, so with 18237 and T_B the stretch is busy 00:45-03:25
    halted = train("HALT", [("SRE", "STOP", H(0, 0), H(0, 5)), ("BAR", "STOP", H(1, 20), H(3, 20)),
                            ("LDH", "STOP", H(6, 0), H(6, 10))])
    data = TrainData([T18237, T_B, halted])
    r = req("b", "DOWN", 139, 148, T(0, 50), H(0, 30))     # may start 00:50-02:50, all inside the busy time
    feasible, rejected = run_step2([r], data, D)
    assert not feasible and rejected[0].step == 2 and "2-hour" in rejected[0].reason


def test_rejected_when_block_runs_past_midnight():
    r = req("c", "UP", 139, 148, T(23, 30), H(1))
    feasible, rejected = run_step2([r], DATA, D)
    assert not feasible and "end of the day" in rejected[0].reason


def test_previous_day_train_crossing_midnight():
    late = train("LATE", [("SRE", "STOP", H(23, 50), H(23, 55)), ("PIL", "PASS", H(24, 5), H(24, 5)),
                          ("LDH", "STOP", H(28, 0), H(28, 10))], days=(2,))   # runs on Tuesday
    data = TrainData([late])
    busy = busy_intervals(data, D, 187, 190, "DOWN")      # D is Wednesday -> Tuesday's train still running
    # Tuesday's train reaches the stretch at 00:01 on Wednesday; the 5-minute margin starts before midnight
    assert busy == [(datetime(2026, 10, 20, 23, 56, 15), T(0, 10))]


def test_not_running_day():
    tue_only = train("TUE", [("SRE", "STOP", H(1), H(1, 5)), ("LDH", "STOP", H(5), H(5, 10))], days=(2,))
    assert busy_intervals(TrainData([tue_only]), D, 50, 60, "DOWN") == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
