# backend/scheduler_routes.py
"""Website endpoints for the Scheduler tab. Every endpoint needs a logged-in user (Bearer token).

Mounted in main.py with prefix "/api", so the addresses are:
  GET  /api/scheduler/state                    what is running now, and when the priority engine last finished
  POST /api/scheduler/priority/run             start the priority engine
  GET  /api/scheduler/priority/status/{id}     progress of that run
  POST /api/scheduler/generate                 start generating + saving the schedule for a date  {"block_date": "YYYY-MM-DD"}
  GET  /api/scheduler/generate/status/{job}    progress of that job (step 1 to 6), and the result
  GET  /api/scheduler/schedule?date=YYYY-MM-DD the saved table for a date

Generating takes up to about 30 seconds, so the button starts a job and the page asks for its
progress every second or two, instead of waiting on one long request (the tunnel could cut it off).
Jobs are kept in memory: restarting the server forgets old job numbers, but saved schedules stay in the database.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from core.database import engine
from core.models import User
from core.security import current_user
from engine_routes import db as priority_db, execute_engine, run_lock as priority_lock
from scheduling_engine.pipeline import run_pipeline

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

gen_lock = threading.Lock()          # only one schedule is generated at a time
JOBS: dict[str, dict] = {}           # job_id -> progress and result (newest last)
CURRENT = {"job_id": None}


class GenerateIn(BaseModel):
    block_date: date


def _trim_jobs() -> None:
    while len(JOBS) > 20:
        JOBS.pop(next(iter(JOBS)))


# ---------------------------------------------------------- priority engine ----

@router.post("/priority/run", status_code=202)
def run_priority(background: BackgroundTasks, user: User = Depends(current_user)):
    if gen_lock.locked():
        raise HTTPException(409, "A schedule is being generated. Wait for it to finish first.")
    if not priority_lock.acquire(blocking=False):
        raise HTTPException(409, "The priority engine is already running.")
    try:
        with priority_db.begin() as conn:
            run_id = conn.execute(
                text("INSERT INTO engine_runs(status) VALUES ('running') RETURNING run_id")).scalar()
    except Exception:
        priority_lock.release()
        raise
    background.add_task(execute_engine, run_id)      # releases priority_lock when it finishes
    return {"run_id": run_id, "status": "running"}


@router.get("/priority/status/{run_id}")
def priority_status(run_id: int, user: User = Depends(current_user)):
    with priority_db.connect() as conn:
        row = conn.execute(text("SELECT status, message FROM engine_runs WHERE run_id = :r"),
                           {"r": run_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Run not found")
    return dict(row)


# ------------------------------------------------------------- generating ----

def _work(job_id: str, block_date: date) -> None:
    job = JOBS[job_id]

    def progress(n: int, label: str) -> None:
        job["step"], job["label"] = n, label

    try:
        res = run_pipeline(engine, block_date, save=True, log=lambda *_: None, progress=progress)
        job.update(status="done" if res.ok else "failed", message=res.message, outcome=res.outcome,
                   run_id=res.run_id, problems=res.problems,
                   summary={"requests": res.n_requests, "granted": res.n_granted,
                            "rejected": res.n_rejected, "not_granted": res.n_not_granted,
                            "blocks": res.n_blocks, "unscored": res.unscored,
                            "priority_run_id": res.priority_run_id})
    except Exception as e:                               # for example: no finished priority run yet
        job.update(status="failed", outcome="ERROR", message=f"{type(e).__name__}: {e}"[:500])
    finally:
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        CURRENT["job_id"] = None
        gen_lock.release()


@router.post("/generate", status_code=202)
def generate(body: GenerateIn, background: BackgroundTasks, user: User = Depends(current_user)):
    if priority_lock.locked():
        raise HTTPException(409, "The priority engine is running. Wait for it to finish first.")
    if not gen_lock.acquire(blocking=False):
        raise HTTPException(409, "A schedule is already being generated. Please wait.")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "status": "running", "step": 0, "label": "Starting",
                    "block_date": body.block_date.isoformat(), "by": user.email,
                    "started_at": datetime.now().isoformat(timespec="seconds"), "started": time.time(),
                    "message": None, "outcome": None, "run_id": None, "problems": [], "summary": None}
    CURRENT["job_id"] = job_id
    _trim_jobs()
    background.add_task(_work, job_id, body.block_date)
    return {"job_id": job_id, "status": "running"}


@router.get("/generate/status/{job_id}")
def generate_status(job_id: str, user: User = Depends(current_user)):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job (the server may have restarted). Open the saved table instead.")
    out = {k: v for k, v in job.items() if k != "started"}
    out["seconds"] = round(time.time() - job["started"], 1)
    return out


@router.get("/state")
def state(user: User = Depends(current_user)):
    with priority_db.connect() as conn:
        last = conn.execute(text(
            "SELECT run_id, finished_at, message FROM engine_runs "
            "WHERE status = 'done' ORDER BY run_id DESC LIMIT 1")).mappings().first()
    return {"generating": gen_lock.locked(), "current_job_id": CURRENT["job_id"],
            "priority_running": priority_lock.locked(),
            "latest_priority": dict(last) if last else None}


# ------------------------------------------------------------ saved table ----

@router.get("/schedule")
def get_schedule(block_date: date = Query(..., alias="date"), user: User = Depends(current_user)):
    with engine.connect() as conn:
        run = conn.execute(text(
            """SELECT run_id, block_date, finished_at, priority_run_id, solver_status, n_requests,
                      n_granted, n_rejected, n_not_granted, n_blocks, total_score,
                      total_block_minutes, total_delay_minutes
               FROM   scheduling.current_runs WHERE block_date = :d"""), {"d": block_date}).mappings().first()
        if run is None:
            return {"run": None, "rows": []}
        rows = conn.execute(text(
            """SELECT block_code, block_no, request_id, department, reason_requested, priority_score,
                      preferred_from, preferred_to, block_km_from, block_km_to, block_start, block_end,
                      slot_start, slot_end, delay_minutes, status, outcome_reason
               FROM   scheduling.current_schedule
               WHERE  run_id = :r
               ORDER  BY (status <> 'GRANTED'), block_start, block_km_from, request_id"""),
            {"r": run["run_id"]}).mappings().all()
    return {"run": dict(run), "rows": [dict(r) for r in rows]}
