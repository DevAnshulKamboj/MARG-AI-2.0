from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import User
from auth.schemas import LoginData, RegisterData, Token, UserOut
from core.security import create_token, current_user, hash_password, verify_password

from datetime import datetime, timedelta
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

router = APIRouter()


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterData, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="That email is already registered.")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(data: LoginData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return Token(access_token=create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user

@router.get("/dashboard-data")
def dashboard_data(user: User = Depends(current_user)):
    return {"message": f"Welcome {user.email}", "stats": []}


class BlockCreate(BaseModel):
    station: str = Field(min_length=1)
    sub_section: str = Field(min_length=1)
    direction: Literal["Up", "Down"]
    line: str = Field(min_length=1)
    km_from: int = Field(ge=0)
    meter_from: int = Field(ge=0, le=999)
    km_to: int = Field(ge=0)
    meter_to: int = Field(ge=0, le=999)
    machine: Literal["Yes", "No"]
    dept: str = Field(min_length=1)
    demanded_for: str = Field(min_length=1)
    demanded_from: datetime
    demanded_to: datetime
    duration: str = Field(min_length=1)   # display text only; the real value is calculated below
    min_duration: int = Field(gt=0)       # minutes
    quantum_of_work: str = Field(min_length=1)
    resource_required: str = Field(min_length=1)
    remarks: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_times(self):
        if self.demanded_to <= self.demanded_from:
            raise ValueError("Demanded To must be after Demanded From.")
        if timedelta(minutes=self.min_duration) > self.demanded_to - self.demanded_from:
            raise ValueError("Minimum Duration cannot be longer than the demanded block duration.")
        return self


@router.post("/block-requests", status_code=201)
def create_block_requests(
    data: BlockCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    location_from = round(data.km_from + data.meter_from / 1000, 3)
    location_to = round(data.km_to + data.meter_to / 1000, 3)
    duration = data.demanded_to - data.demanded_from
    min_duration = timedelta(minutes=data.min_duration)

    sr_no = db.execute(text("SELECT nextval('block_requests_sr_no_seq')")).scalar()
    block_id = f"NR-BLK-{datetime.now().year}-{sr_no:03d}"
    db.execute(
        text("""
            INSERT INTO block_requests (
                sr_no, block_id, station, sub_section, direction, line,
                location_from, location_to, machine, dept, block_demanded_for,
                demanded_from, demanded_to, duration, min_duration,
                quantum_of_work, resource_required, remarks
            ) VALUES (
                :sr_no, :block_id, :station, :sub_section, :direction, :line,
                :location_from, :location_to, :machine, :dept, :reason,
                :demanded_from, :demanded_to, :duration, :min_duration,
                :quantum, :resource, :remarks
            )
        """),
        {
            "sr_no": sr_no,
            "block_id": block_id,
            "station": data.station,
            "sub_section": data.sub_section,
            "direction": data.direction,
            "line": data.line,
            "location_from": location_from,
            "location_to": location_to,
            "machine": data.machine,
            "dept": data.dept,
            "reason": data.demanded_for,
            "demanded_from": data.demanded_from,
            "demanded_to": data.demanded_to,
            "duration": duration,
            "min_duration": min_duration,
            "quantum": data.quantum_of_work,
            "resource": data.resource_required,
            "remarks": data.remarks,
        },
    )
    db.commit()
    return {"message": "Block demand saved."}