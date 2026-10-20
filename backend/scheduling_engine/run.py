"""Run Steps 1 and 2 for one block date and print what happened (nothing is saved yet).

From the backend folder, with the venv active:
    python -m scheduling_engine.run --date 2026-10-22
"""
from __future__ import annotations

import argparse
from datetime import date

from .step1_load_requests import run_step1
from .step2_feasibility import load_train_data, run_step2


def main() -> None:
    ap = argparse.ArgumentParser(description="MARG-AI scheduling engine, Steps 1-2 (dry run)")
    ap.add_argument("--date", required=True, help="block date D, YYYY-MM-DD")
    block_date = date.fromisoformat(ap.parse_args().date)

    from core.database import engine          # imported here so tests need no DATABASE_URL

    with engine.connect() as conn:
        s1 = run_step1(conn, block_date)
        data = load_train_data(conn)

    feasible, rej2 = run_step2(s1.valid, data, block_date)

    print(f"Block date {block_date}, priority run {s1.run_id}")
    print(f"Step 1: {len(s1.valid)} valid, {len(s1.rejected)} invalid")
    for r in s1.rejected:
        print(f"   INVALID   {r.block_id}: {r.reason}")
    print(f"Step 2: {len(feasible)} feasible, {len(rej2)} rejected")
    for f in feasible:
        q = f.request
        print(f"   FEASIBLE  {q.block_id}  {q.direction} {q.lo:g}-{q.hi:g} km  "
              f"{q.duration}  starts {f.starts[0]:%H:%M}..{f.starts[-1]:%H:%M} ({len(f.starts)} options)")
    for r in rej2:
        print(f"   REJECTED  {r.block_id}: {r.reason}")


if __name__ == "__main__":
    main()
