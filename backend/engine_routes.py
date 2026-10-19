# backend/engine_routes.py
import os
import subprocess
import threading
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy import create_engine, text

load_dotenv()

router = APIRouter(prefix="/engine", tags=["engine"])

db = create_engine(os.getenv("DATABASE_URL"))

BASE = Path(__file__).parent
R_SCRIPT = BASE / "priority_engine" / "priority_engine.R"
OUT_DIR = BASE / "output"
OUT_DIR.mkdir(exist_ok=True)

run_lock = threading.Lock()


def check_key(x_api_key: str = Header(None)):
    if x_api_key != os.getenv("ENGINE_API_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")


def execute_engine(run_id: int):
    csv_path = OUT_DIR / f"ranking_{run_id}.csv"
    try:
        proc = subprocess.run(
            [os.getenv("RSCRIPT_PATH", "Rscript"), str(R_SCRIPT), str(csv_path)],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(BASE / "priority_engine"),
        )
        if proc.returncode != 0:
            raise RuntimeError("R failed: " + proc.stderr[-500:])

        df = pd.read_csv(csv_path)
        required = {"block_id", "topsis_score", "rank"}
        if not required.issubset(df.columns):
            raise ValueError(f"CSV missing columns: {required - set(df.columns)}")
        if df.empty:
            raise ValueError("CSV is empty")
        if df["block_id"].duplicated().any():
            raise ValueError("CSV has duplicate block_id values")

        df = df[["block_id", "topsis_score", "rank"]].copy()
        df["run_id"] = run_id

        with db.begin() as conn:
            df.to_sql("priority_ranking", conn, if_exists="append", index=False)
            conn.execute(
                text(
                    "UPDATE engine_runs SET status='done', finished_at=now(), "
                    "message=:m WHERE run_id=:r"
                ),
                {"m": f"{len(df)} requests ranked", "r": run_id},
            )
    except Exception as e:
        with db.begin() as conn:
            conn.execute(
                text(
                    "UPDATE engine_runs SET status='failed', finished_at=now(), "
                    "message=:m WHERE run_id=:r"
                ),
                {"m": str(e)[:500], "r": run_id},
            )
    finally:
        run_lock.release()


@router.post("/run", dependencies=[Depends(check_key)])
def run_engine(background: BackgroundTasks):
    if not run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Engine is already running")
    try:
        with db.begin() as conn:
            run_id = conn.execute(
                text("INSERT INTO engine_runs(status) VALUES ('running') RETURNING run_id")
            ).scalar()
    except Exception:
        run_lock.release()
        raise
    background.add_task(execute_engine, run_id)
    return {"run_id": run_id, "status": "running"}


@router.get("/status/{run_id}", dependencies=[Depends(check_key)])
def status(run_id: int):
    with db.connect() as conn:
        row = conn.execute(
            text("SELECT status, message FROM engine_runs WHERE run_id=:r"),
            {"r": run_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


@router.get("/ranking", dependencies=[Depends(check_key)])
def latest_ranking():
    q = text(
        """
        SELECT p.rank,
               p.block_id,
               b.dept               AS department,
               b.block_demanded_for AS reason,
               b.demanded_from::date AS requested_date,
               p.topsis_score,
               p.generated_at
        FROM priority_ranking p
        LEFT JOIN block_requests b ON b.block_id = p.block_id
        WHERE p.run_id = (SELECT max(run_id) FROM engine_runs WHERE status = 'done')
        ORDER BY p.rank
        """
    )
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]