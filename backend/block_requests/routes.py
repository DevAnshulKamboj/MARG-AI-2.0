from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import User
from core.security import current_user

router = APIRouter()


@router.get("/block-requests")
def list_block_requests(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    rows = db.execute(
        text("SELECT * FROM public.block_requests ORDER BY sr_no")
    ).mappings().all()
    return [dict(r) for r in rows]