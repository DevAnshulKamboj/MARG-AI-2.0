"""The whole scheduling run (Steps 1 to 6) in one function.

Both the terminal (run.py) and the website (scheduler_routes.py) call run_pipeline(), so they
can never drift apart. It never raises for an ordinary failure (validation failed, save failed,
solver missing): it returns a PipelineResult saying what happened. Unexpected errors, such as
"no finished priority run", are raised as normal exceptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from .step1_load_requests import run_step1
from .step2_feasibility import load_train_data, run_step2
from .step3_candidates import run_step3
from .step4_optimize import run_step4
from .step5_validate import ValidationFailed, run_step5
from .step6_save import fetch_table, format_table, log_failed_run, save_run

NO_SCORE_TEXT = "no priority score"


@dataclass
class PipelineResult:
    ok: bool
    outcome: str            # SAVED, DRY_RUN, VALIDATION_FAILED, SAVE_FAILED or NO_SOLVER
    message: str            # one or two plain sentences for the person using the tool
    block_date: date
    priority_run_id: int | None = None
    run_id: int | None = None            # scheduling run saved (SAVED only)
    n_requests: int = 0
    n_granted: int = 0
    n_rejected: int = 0                  # invalid or no train-free window (Steps 1 and 2)
    n_not_granted: int = 0               # feasible but not selected (Step 4)
    n_blocks: int = 0
    unscored: int = 0                    # requests rejected only because they have no priority score yet
    problems: list[str] = field(default_factory=list)
    table_text: str = ""


def run_pipeline(engine, block_date: date, save: bool = False,
                 log: Callable[[str], None] = print,
                 progress: Callable[[int, str], None] | None = None) -> PipelineResult:
    def step(n: int, label: str) -> None:
        if progress:
            progress(n, label)

    step(1, "Loading and checking the requests")
    with engine.connect() as conn:
        s1 = run_step1(conn, block_date)
        data = load_train_data(conn)

    step(2, "Checking each request against the train timetables")
    feasible, rej2 = run_step2(s1.valid, data, block_date)
    rejected = s1.rejected + rej2
    unscored = sum(1 for r in s1.rejected if r.reason.startswith(NO_SCORE_TEXT))

    facts = dict(block_date=block_date, priority_run_id=s1.run_id,
                 n_requests=len(s1.valid) + len(s1.rejected), n_rejected=len(rejected), unscored=unscored)
    hint = (f" {unscored} request(s) have no priority score yet: run the priority engine, then generate again."
            if unscored else "")

    log(f"Block date {block_date}, priority run {s1.run_id}")
    log(f"Step 1: {len(s1.valid)} valid, {len(s1.rejected)} invalid")
    for r in s1.rejected:
        log(f"   INVALID   {r.block_id}: {r.reason}")
    log(f"Step 2: {len(feasible)} feasible, {len(rej2)} rejected")
    for f in feasible:
        q = f.request
        log(f"   FEASIBLE  {q.block_id}  {q.direction} {q.lo:g}-{q.hi:g} km  "
            f"{q.duration}  starts {f.starts[0]:%H:%M}..{f.starts[-1]:%H:%M} ({len(f.starts)} options)")
    for r in rej2:
        log(f"   REJECTED  {r.block_id}: {r.reason}")

    step(3, "Building the possible blocks")
    s3 = run_step3(feasible, data, block_date)
    log(f"Step 3: {len(s3.candidates)} candidates ({s3.n_single} stand-alone, {s3.n_shared} shared)")
    log(f"        {s3.groups_tried} request groups passed the sharing rules, "
        f"{s3.groups_blocked_by_trains} of them had no train-free slot")
    groups: dict[tuple, list] = {}
    for c in s3.candidates:
        if len(c.request_ids) > 1:
            groups.setdefault(c.request_ids, []).append(c)
    for ids, cs in sorted(groups.items()):
        first = min(cs, key=lambda c: c.end - c.start)
        log(f"   SHARED    {' + '.join(ids)}  {first.lo:g}-{first.hi:g} km  {len(cs)} options, "
            f"shortest {first.start:%H:%M}-{first.end:%H:%M}")

    step(4, "Choosing the best blocks (solver)")
    try:
        s4 = run_step4(feasible, s3.candidates)
    except ImportError:
        msg = "OR-Tools is not installed in this environment (pip install ortools)"
        log(f"Step 4: {msg}")
        return PipelineResult(ok=False, outcome="NO_SOLVER", message=msg, **facts)
    names = {a.block_id: a for a in s4.assignments}
    log(f"Step 4: {s4.status} in {s4.seconds:.1f} s - granted {len(s4.assignments)} of {len(feasible)} "
        f"feasible requests, score {s4.total_score}, {s4.n_blocks} blocks, "
        f"{s4.total_block_minutes / 60:.2f} block hours, delay {s4.total_delay_minutes} min")
    for b in s4.blocks:
        work = ", ".join(f"{rid[-3:]} ({names[rid].start:%H:%M}-{names[rid].end:%H:%M})"
                         for rid in b.request_ids)
        log(f"   BLOCK {b.block_no:<3} {b.lo:g}-{b.hi:g} km  {b.start:%H:%M}-{b.end:%H:%M}  {work}")
    for rid in s4.unassigned:
        log(f"   NOT GRANTED  {rid}: another block took its place (the reason is saved with --save)")
    counts = dict(n_granted=len(s4.assignments), n_not_granted=len(s4.unassigned), n_blocks=s4.n_blocks)

    step(5, "Checking the result independently")
    try:
        with engine.connect() as conn:
            s5 = run_step5(conn, block_date, s4, rejected)
    except ValidationFailed as e:
        log(f"Step 5: VALIDATION FAILED - {len(e.violations)} problem(s). Nothing is saved.")
        for problem in e.violations[:50]:
            log(f"   {problem}")
        if save:
            try:
                log_failed_run(engine, block_date, s1.run_id,
                               f"Validation failed: {len(e.violations)} problem(s). First: {e.violations[0]}")
                log("        The failed run was logged in scheduling.scheduling_runs (no blocks saved).")
            except Exception:
                pass
        return PipelineResult(ok=False, outcome="VALIDATION_FAILED",
                              message=f"The checks found {len(e.violations)} problem(s), so nothing was saved.",
                              problems=list(e.violations[:50]), **facts, **counts)
    log(f"Step 5: PASSED - {s5.blocks_checked} blocks and {s5.assignments_checked} granted requests "
        f"checked against {s5.trains_checked} trains")

    if not save:
        log("Step 6: DRY RUN - nothing saved. Add --save to save this result.")
        return PipelineResult(ok=True, outcome="DRY_RUN", message="Dry run: nothing was saved." + hint,
                              **facts, **counts)

    step(6, "Saving the schedule")
    try:
        run_id = save_run(engine, block_date, s1.run_id, s1.valid, rejected, feasible, s4)
    except Exception as e:                        # the transaction was rolled back: nothing was kept
        log(f"Step 6: SAVE FAILED - nothing was saved, the earlier result for {block_date} is unchanged.")
        log(f"   {type(e).__name__}: {e}")
        try:
            log_failed_run(engine, block_date, s1.run_id, f"Save failed: {type(e).__name__}: {e}")
        except Exception:
            pass
        return PipelineResult(ok=False, outcome="SAVE_FAILED",
                              message=f"Saving failed ({type(e).__name__}). Nothing was changed; "
                                      f"the earlier result for {block_date} is untouched.",
                              problems=[str(e)[:500]], **facts, **counts)

    log(f"Step 6: SAVED as scheduling run {run_id} for {block_date}. "
        f"Any earlier saved result for this date was replaced.")
    table = format_table(fetch_table(engine, run_id))
    log("")
    log(table)
    return PipelineResult(
        ok=True, outcome="SAVED", run_id=run_id, table_text=table,
        message=(f"Saved: {counts['n_granted']} of {facts['n_requests']} requests granted in "
                 f"{counts['n_blocks']} blocks." + hint),
        **facts, **counts)
