"""Checks for Step 6 and the pipeline (no database needed). Run from backend:  python -m scheduling_engine.test_step6"""
from datetime import date
from unittest import mock

from . import pipeline
from .models import Assignment, ChosenBlock, FeasibleRequest, Rejection, Request, Step4Result
from .step1_load_requests import Step1Result
from .step5_validate import Step5Result, ValidationFailed
from .step6_save import block_code, build_outcomes, format_table, not_granted_reason, save_run
from .test_steps_1_2 import D, DATA, H, T


def rq(bid, lo, hi, score=0.5, start=T(14)):
    return Request(bid, "S&T", "test", None, "DOWN", 2, lo, hi, start, None, H(1), score, 1)


def fr(r):
    return FeasibleRequest(r, [], [r.preferred_start + H(0, 5 * i) for i in range(25)])


def result(blocks, assigns, unassigned):
    return Step4Result("OPTIMAL", blocks, assigns, unassigned, 0, 0, len(blocks), 0, 0.1)


class FakeResult:
    def scalar(self):
        return 7


class FakeConn:
    def __init__(self, log):
        self.log = log

    def execute(self, stmt, params=None):
        self.log.append((" ".join(str(stmt).split()), params))
        return FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeEngine:
    def __init__(self):
        self.log = []

    def connect(self):
        return FakeConn(self.log)

    def begin(self):
        return FakeConn(self.log)


# ------------------------------------------------------------ Step 6 ----

def test_block_code():
    assert block_code(date(2026, 11, 2), 1) == "SCH-2026-11-02-01"
    assert block_code(date(2026, 11, 2), 12) == "SCH-2026-11-02-12"


def test_every_request_gets_one_outcome_and_reasons():
    a, b, c = rq("a", 20, 22, 0.9), rq("b", 20, 22, 0.2), rq("c", 40, 41, 0.4)
    feasible = [fr(a), fr(b), fr(c)]
    blocks = [ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), ("a",))]
    assigns = [Assignment("a", 1, T(14), T(15), 0)]
    s4 = result(blocks, assigns, ["b", "c"])
    outs = build_outcomes(D, [a, b, c], [Rejection("x", 1, "from and to location are the same")], feasible, s4)
    by = {o.request_id: o for o in outs}
    assert sorted(by) == ["a", "b", "c", "x"] and len(outs) == 4
    assert by["a"].outcome == "GRANTED" and by["a"].reason is None and by["a"].block_no == 1
    assert by["a"].score == 0.9 and by["a"].delay_minutes == 0
    assert by["b"].outcome == "NOT_GRANTED" and "SCH-2026-10-21-01" in by["b"].reason
    assert by["c"].outcome == "NOT_GRANTED" and by["c"].reason and "SCH-" not in by["c"].reason
    assert by["x"].outcome == "REJECTED" and by["x"].score is None


def test_non_granted_always_have_a_reason_and_no_block():
    a = rq("a", 20, 22)
    s4 = result([], [], ["a"])
    o = build_outcomes(D, [a], [], [fr(a)], s4)[0]
    assert o.reason and o.block_no is None and not_granted_reason(fr(a), s4, D)


def test_table_prints():
    rows = [{"request_id": "NR-BLK-2026-001", "dept": "S&T", "topsis_score": 0.9, "demanded_from": T(14),
             "outcome": "GRANTED", "reason": None, "block_code": "SCH-2026-10-21-01", "km_from": 20,
             "km_to": 22, "start_time": T(14), "end_time": T(15), "slot_start": T(14), "slot_end": T(15),
             "delay_minutes": 0},
            {"request_id": "NR-BLK-2026-002", "dept": "ENG", "topsis_score": None, "demanded_from": T(14),
             "outcome": "REJECTED", "reason": "no train-free window", "block_code": None, "km_from": None,
             "km_to": None, "start_time": None, "end_time": None, "slot_start": None, "slot_end": None,
             "delay_minutes": None}]
    text = format_table(rows)
    assert "GRANTED" in text and "20-22" in text and "no train-free window" in text


def test_old_result_is_deleted_before_new_blocks_are_inserted():
    """The bug that made the second save fail: block codes are unique, so the old blocks must go first."""
    a = rq("a", 20, 22)
    s4 = result([ChosenBlock(1, 1, 2, 20, 22, T(14), T(15), ("a",))], [Assignment("a", 1, T(14), T(15), 0)], [])
    eng = FakeEngine()
    assert save_run(eng, D, 5, [a], [], [fr(a)], s4) == 7
    sqls = [s for s, _ in eng.log]

    def first(prefix):
        return next(i for i, s in enumerate(sqls) if s.startswith(prefix))

    assert first("INSERT INTO scheduling.scheduling_runs") == 0
    assert first("DELETE FROM scheduling.request_outcomes") < first("DELETE FROM scheduling.scheduled_blocks") \
        < first("DELETE FROM scheduling.scheduling_runs") < first("INSERT INTO scheduling.scheduled_blocks")
    assert first("INSERT INTO scheduling.scheduled_blocks") < first("INSERT INTO scheduling.request_outcomes")
    assert sqls[-1].startswith("UPDATE scheduling.scheduling_runs SET status = 'done'")


# ---------------------------------------------------------- pipeline ----

def _fake_s4(reqs):
    blocks = [ChosenBlock(i + 1, i + 1, 2, r.lo, r.hi, T(14), T(15), (r.block_id,)) for i, r in enumerate(reqs)]
    assigns = [Assignment(r.block_id, i + 1, T(14), T(15), 0) for i, r in enumerate(reqs)]
    return Step4Result("OPTIMAL", blocks, assigns, [], 1000, 120, 2, 0, 0.1)


def _run(save=True, rejected1=(), step5=None, save_error=None):
    reqs = [rq("a", 20, 22, 0.9), rq("b", 40, 41, 0.4)]
    s1 = Step1Result(5, D, reqs, list(rejected1))
    saved, failed, lines, steps = [], [], [], []
    patches = [
        mock.patch.object(pipeline, "run_step1", return_value=s1),
        mock.patch.object(pipeline, "load_train_data", return_value=DATA),
        mock.patch.object(pipeline, "run_step4", return_value=_fake_s4(reqs)),
        mock.patch.object(pipeline, "run_step5",
                          **({"side_effect": step5} if step5 else {"return_value": Step5Result(True, 2, 2, 2)})),
        mock.patch.object(pipeline, "save_run",
                          **({"side_effect": save_error} if save_error else {"return_value": 9})),
        mock.patch.object(pipeline, "fetch_table", return_value=[]),
        mock.patch.object(pipeline, "log_failed_run", side_effect=lambda *a: failed.append(a)),
    ]
    for p in patches:
        p.start()
    try:
        res = pipeline.run_pipeline(FakeEngine(), D, save=save, log=lines.append,
                                    progress=lambda n, t: steps.append(n))
    finally:
        for p in patches:
            p.stop()
    return res, failed, lines, steps


def test_pipeline_dry_run_saves_nothing():
    res, failed, lines, steps = _run(save=False)
    assert res.ok and res.outcome == "DRY_RUN" and res.run_id is None
    assert steps == [1, 2, 3, 4, 5] and any("DRY RUN" in l for l in lines)


def test_pipeline_saves_and_reports_progress():
    res, failed, lines, steps = _run(save=True)
    assert res.ok and res.outcome == "SAVED" and res.run_id == 9
    assert res.n_granted == 2 and res.n_blocks == 2 and res.n_requests == 2
    assert steps == [1, 2, 3, 4, 5, 6] and failed == []


def test_pipeline_validation_failure_saves_nothing_and_logs():
    res, failed, lines, steps = _run(save=True, step5=ValidationFailed(["block 1 clashes with train X"]))
    assert not res.ok and res.outcome == "VALIDATION_FAILED" and res.problems == ["block 1 clashes with train X"]
    assert len(failed) == 1 and 6 not in steps


def test_pipeline_save_failure_is_reported_not_raised():
    res, failed, lines, steps = _run(save=True, save_error=RuntimeError("boom"))
    assert not res.ok and res.outcome == "SAVE_FAILED" and "untouched" in res.message
    assert len(failed) == 1


def test_pipeline_flags_requests_without_a_priority_score():
    rej = [Rejection("z", 1, "no priority score for this request")]
    res, *_ = _run(save=True, rejected1=rej)
    assert res.unscored == 1 and "priority engine" in res.message


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
