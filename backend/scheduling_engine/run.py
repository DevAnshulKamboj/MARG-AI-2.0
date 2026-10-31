"""Run the scheduling engine (Steps 1 to 6) for one block date from the terminal.

From the backend folder, with the venv active:
    python -m scheduling_engine.run --date 2026-11-02            (dry run: shows everything, saves nothing)
    python -m scheduling_engine.run --date 2026-11-02 --save     (also saves the result in the database)

The steps themselves live in pipeline.py, which the website uses too.
"""
from __future__ import annotations

import argparse
from datetime import date

from .pipeline import run_pipeline


def main() -> None:
    ap = argparse.ArgumentParser(description="MARG-AI scheduling engine, Steps 1-6")
    ap.add_argument("--date", required=True, help="block date D, YYYY-MM-DD")
    ap.add_argument("--save", action="store_true",
                    help="save the result (Step 6). Without this flag nothing is written.")
    args = ap.parse_args()
    block_date = date.fromisoformat(args.date)

    from core.database import engine          # imported here so tests need no DATABASE_URL

    result = run_pipeline(engine, block_date, save=args.save, log=print)
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
