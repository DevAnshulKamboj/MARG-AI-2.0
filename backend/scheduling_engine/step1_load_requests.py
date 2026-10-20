"""Step 1 - load the day's block requests and check each one is valid.

Invalid requests are not dropped silently: each gets a Rejection with a reason,
which Step 6 will save, so every request ends with exactly one outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text

from .config import DIRECTION_TO_LINE
from .models import Rejection, Request


@dataclass
class Step1Result:
    run_id: int                      # priority-engine run whose scores were used
    block_date: date
    valid: list[Request]
    rejected: list[Rejection]


# ---------------------------------------------------------------- database ----

def latest_priority_run(conn) -> int:
    run_id = conn.execute(
        text("SELECT max(run_id) FROM engine_runs WHERE status = 'done'")
    ).scalar()
    if run_id is None:
        raise RuntimeError("No finished priority run found. Run the priority engine first.")
    return run_id


def chainage_bounds(conn) -> tuple[float, float]:
    lo, hi = conn.execute(
        text("SELECT min(chainage_km), max(chainage_km) FROM infra.stations")
    ).one()
    return float(lo), float(hi)


def load_raw_requests(conn, block_date: date, run_id: int) -> list[dict]:
    """Requests whose preferred start falls on block_date, with their priority score."""
    rows = conn.execute(
        text(
            """
            SELECT b.block_id, b.dept, b.block_demanded_for AS reason, b.sub_section,
                   b.direction, b.location_from, b.location_to,
                   b.demanded_from, b.demanded_to, b.duration,
                   p.topsis_score, p."rank" AS rank
            FROM   block_requests b
            LEFT JOIN priority_ranking p
                   ON p.block_id = b.block_id AND p.run_id = :run_id
            WHERE  b.demanded_from >= :d0 AND b.demanded_from < :d1
            ORDER  BY b.demanded_from, b.block_id
            """
        ),
        {"run_id": run_id, "d0": block_date, "d1": block_date + timedelta(days=1)},
    )
    return [dict(r) for r in rows.mappings()]


# -------------------------------------------------------------- validation ----

def validate_requests(rows: list[dict], block_date: date,
                      min_chainage: float, max_chainage: float
                      ) -> tuple[list[Request], list[Rejection]]:
    """Pure function: no database access, so it can be tested on its own."""
    valid: list[Request] = []
    rejected: list[Rejection] = []

    for r in rows:
        bid = r["block_id"]

        def reject(reason: str):
            rejected.append(Rejection(bid, 1, reason))

        direction = (r.get("direction") or "").strip().upper()
        if direction not in DIRECTION_TO_LINE:
            reject(f"direction '{r.get('direction')}' is not Up or Down")
            continue

        if r.get("location_from") is None or r.get("location_to") is None:
            reject("from or to location is missing")
            continue
        a, b = float(r["location_from"]), float(r["location_to"])
        lo, hi = min(a, b), max(a, b)          # stretch runs from lower to higher chainage
        if lo == hi:
            reject("from and to location are the same")
            continue
        if lo < min_chainage or hi > max_chainage:
            reject(f"location {lo:g}-{hi:g} km is outside the loaded line "
                   f"({min_chainage:g}-{max_chainage:g} km)")
            continue

        duration = r.get("duration")
        if duration is None or duration <= timedelta(0):
            reject("duration is missing or not above zero")
            continue

        start = r.get("demanded_from")
        if start is None or start.date() != block_date:
            reject(f"preferred start does not fall on {block_date}")
            continue

        if r.get("topsis_score") is None:
            reject("no priority score for this request")
            continue

        valid.append(Request(
            block_id=bid,
            dept=r.get("dept"),
            reason=r.get("reason"),
            sub_section=r.get("sub_section"),
            direction=direction,
            line=DIRECTION_TO_LINE[direction],
            lo=lo, hi=hi,
            preferred_start=start,
            preferred_end=r.get("demanded_to"),
            duration=duration,
            score=float(r["topsis_score"]),
            rank=r.get("rank"),
        ))
    return valid, rejected


def run_step1(conn, block_date: date) -> Step1Result:
    run_id = latest_priority_run(conn)
    lo, hi = chainage_bounds(conn)
    rows = load_raw_requests(conn, block_date, run_id)
    valid, rejected = validate_requests(rows, block_date, lo, hi)
    return Step1Result(run_id, block_date, valid, rejected)
