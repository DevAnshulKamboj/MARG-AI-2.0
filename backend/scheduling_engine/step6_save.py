"""Step 6 - save the validated schedule and show it as a table.

Only called after Step 5 has passed. Everything is written in ONE database transaction:
if any part fails, nothing is kept and the earlier saved result for the date stays as it was.

What is saved (tables from 001_scheduling_schema.sql and 002_block_codes.sql)
  * scheduling.scheduling_runs   one row for this run, with the totals
  * scheduling.scheduled_blocks  the real blocks, each with a permanent code such as SCH-2026-11-02-01
  * scheduling.request_outcomes  exactly one row per request: GRANTED, REJECTED or NOT_GRANTED, with a reason
  * public.block_requests        unassigned_at / unassigned_reason filled for every request that got no
                                 block, and cleared for every request that did
Re-running a date replaces that date's earlier saved result (inside the same transaction).
A failed run is only logged in scheduling_runs (status 'failed'); it never saves blocks or outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text

from .models import FeasibleRequest, Rejection, Request, Step4Result


@dataclass(frozen=True)
class Outcome:
    request_id: str
    outcome: str                       # GRANTED, REJECTED or NOT_GRANTED
    reason: str | None                 # always set unless GRANTED
    score: float | None
    block_no: int | None = None
    slot_start: datetime | None = None
    slot_end: datetime | None = None
    delay_minutes: int | None = None


def block_code(block_date: date, block_no: int) -> str:
    return f"SCH-{block_date:%Y-%m-%d}-{block_no:02d}"


# ------------------------------------------------------------ pure part ----

def not_granted_reason(f: FeasibleRequest, s4: Step4Result, block_date: date) -> str:
    """Why a feasible request was left out: name the chosen blocks that sit on its stretch and times."""
    r = f.request
    w0, w1 = f.starts[0], f.starts[-1] + r.duration
    hits = [b for b in s4.blocks
            if b.line == r.line and b.lo <= r.hi and r.lo <= b.hi and b.start < w1 and w0 < b.end]
    if hits:
        names = "; ".join(f"{block_code(block_date, b.block_no)} ({b.lo:g}-{b.hi:g} km, "
                          f"{b.start:%H:%M}-{b.end:%H:%M})" for b in hits)
        return (f"Not selected: blocks given to other requests overlap its stretch during its possible "
                f"times ({w0:%H:%M}-{w1:%H:%M}): {names}. The schedule with the best total priority "
                f"score was kept.")
    return ("Not selected: the schedule with the best total priority score left it out, because every "
            "slot it could use clashes with a block chosen for other requests.")


def build_outcomes(block_date: date, valid: list[Request], rejected: list[Rejection],
                   feasible: list[FeasibleRequest], s4: Step4Result) -> list[Outcome]:
    score = {r.block_id: r.score for r in valid}
    by_id = {f.request.block_id: f for f in feasible}
    out: list[Outcome] = []
    for a in s4.assignments:
        out.append(Outcome(a.block_id, "GRANTED", None, score.get(a.block_id), a.block_no,
                           a.start, a.end, a.delay_minutes))
    for rid in s4.unassigned:
        out.append(Outcome(rid, "NOT_GRANTED", not_granted_reason(by_id[rid], s4, block_date),
                           score.get(rid)))
    for rj in rejected:
        out.append(Outcome(rj.block_id, "REJECTED", rj.reason, score.get(rj.block_id)))
    return out


# -------------------------------------------------------------- database ----

def save_run(engine, block_date: date, priority_run_id: int, valid: list[Request],
             rejected: list[Rejection], feasible: list[FeasibleRequest], s4: Step4Result) -> int:
    """Save everything in one transaction. Returns the new run_id."""
    outcomes = build_outcomes(block_date, valid, rejected, feasible, s4)
    n_granted = sum(o.outcome == "GRANTED" for o in outcomes)
    with engine.begin() as conn:
        run_id = conn.execute(text(
            "INSERT INTO scheduling.scheduling_runs (block_date, status, priority_run_id) "
            "VALUES (:d, 'running', :p) RETURNING run_id"),
            {"d": block_date, "p": priority_run_id}).scalar()

        # replace: remove the earlier saved result for this date FIRST (block codes must be unique, so
        # the old blocks have to go before the new ones are inserted). Failed-run log rows are kept.
        # This is still the same transaction: if anything below fails, the old result comes back.
        old = "(SELECT run_id FROM scheduling.scheduling_runs " \
              "WHERE block_date = :d AND status = 'done' AND run_id <> :run)"
        p = {"d": block_date, "run": run_id}
        conn.execute(text(f"DELETE FROM scheduling.request_outcomes WHERE run_id IN {old}"), p)
        conn.execute(text(f"DELETE FROM scheduling.scheduled_blocks WHERE run_id IN {old}"), p)
        conn.execute(text("DELETE FROM scheduling.scheduling_runs "
                          "WHERE block_date = :d AND status = 'done' AND run_id <> :run"), p)

        if s4.blocks:
            conn.execute(text(
                """INSERT INTO scheduling.scheduled_blocks
                   (run_id, block_no, block_code, line, km_from, km_to, start_time, end_time, block_minutes)
                   VALUES (:run, :no, :code, :line, :lo, :hi, :s, :e, :mins)"""),
                [{"run": run_id, "no": b.block_no, "code": block_code(block_date, b.block_no),
                  "line": b.line, "lo": b.lo, "hi": b.hi, "s": b.start, "e": b.end,
                  "mins": int((b.end - b.start).total_seconds() // 60)} for b in s4.blocks])

        if outcomes:
            conn.execute(text(
                """INSERT INTO scheduling.request_outcomes
                   (run_id, request_id, outcome, reason, topsis_score, block_no,
                    slot_start, slot_end, delay_minutes)
                   VALUES (:run, :rid, :out, :reason, :score, :no, :s, :e, :delay)"""),
                [{"run": run_id, "rid": o.request_id, "out": o.outcome, "reason": o.reason,
                  "score": o.score, "no": o.block_no, "s": o.slot_start, "e": o.slot_end,
                  "delay": o.delay_minutes} for o in outcomes])

            # the two "couldn't assign" columns on the request table
            failed = [{"rid": o.request_id, "reason": o.reason} for o in outcomes if o.outcome != "GRANTED"]
            ok = [{"rid": o.request_id} for o in outcomes if o.outcome == "GRANTED"]
            if failed:
                conn.execute(text("UPDATE public.block_requests SET unassigned_at = now(), "
                                  "unassigned_reason = :reason WHERE block_id = :rid"), failed)
            if ok:
                conn.execute(text("UPDATE public.block_requests SET unassigned_at = NULL, "
                                  "unassigned_reason = NULL WHERE block_id = :rid"), ok)

        conn.execute(text(
            """UPDATE scheduling.scheduling_runs SET status = 'done', finished_at = now(),
                      solver_status = :st, solve_seconds = :sec, n_requests = :nreq, n_granted = :ng,
                      n_rejected = :nrej, n_not_granted = :nng, n_blocks = :nb, total_score = :ts,
                      total_block_minutes = :tm, total_delay_minutes = :td
               WHERE run_id = :run"""),
            {"st": s4.status, "sec": round(s4.seconds, 2), "nreq": len(outcomes), "ng": n_granted,
             "nrej": len(rejected), "nng": len(s4.unassigned), "nb": s4.n_blocks,
             "ts": s4.total_score, "tm": s4.total_block_minutes, "td": s4.total_delay_minutes,
             "run": run_id})
    return run_id


def log_failed_run(engine, block_date: date, priority_run_id: int | None, message: str) -> None:
    """Record a failed run. Saves no blocks or outcomes."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO scheduling.scheduling_runs (block_date, status, finished_at, priority_run_id, message) "
            "VALUES (:d, 'failed', now(), :p, :m)"),
            {"d": block_date, "p": priority_run_id, "m": message[:2000]})


# ----------------------------------------------------------------- table ----

def fetch_table(engine, run_id: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            """SELECT o.request_id, b.dept, o.topsis_score, b.demanded_from, o.outcome, o.reason,
                      sb.block_code, sb.km_from, sb.km_to, sb.start_time, sb.end_time,
                      o.slot_start, o.slot_end, o.delay_minutes
               FROM   scheduling.request_outcomes o
               LEFT   JOIN public.block_requests b ON b.block_id = o.request_id
               LEFT   JOIN scheduling.scheduled_blocks sb
                      ON sb.run_id = o.run_id AND sb.block_no = o.block_no
               WHERE  o.run_id = :run
               ORDER  BY (o.outcome <> 'GRANTED'), sb.start_time, sb.km_from, o.request_id"""),
            {"run": run_id}).mappings()
        return [dict(r) for r in rows]


def format_table(rows: list[dict]) -> str:
    """Plain-text table: granted requests first (by block time), then the ones without a block."""
    def hm(t):
        return f"{t:%H:%M}" if t else "-"

    head = ["Request", "Dept", "Score", "Asked", "Status", "Block", "Km", "Block time", "Work slot", "Delay"]
    body = []
    for r in rows:
        km = f"{float(r['km_from']):g}-{float(r['km_to']):g}" if r["km_from"] is not None else "-"
        score = f"{float(r['topsis_score']):.3f}" if r["topsis_score"] is not None else "-"
        body.append([r["request_id"], r["dept"] or "-", score, hm(r["demanded_from"]), r["outcome"],
                     (r["block_code"] or "-")[-13:], km,
                     f"{hm(r['start_time'])}-{hm(r['end_time'])}" if r["start_time"] else "-",
                     f"{hm(r['slot_start'])}-{hm(r['slot_end'])}" if r["slot_start"] else "-",
                     f"{r['delay_minutes']} min" if r["delay_minutes"] is not None else "-"])
    widths = [max(len(str(x[i])) for x in [head] + body) for i in range(len(head))]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    out = [line(head), "  ".join("-" * w for w in widths)] + [line(b) for b in body]
    why = [f"   {r['request_id']}: {r['reason']}" for r in rows if r["outcome"] != "GRANTED"]
    if why:
        out += ["", "Why some requests got no block:"] + why
    return "\n".join(out)
