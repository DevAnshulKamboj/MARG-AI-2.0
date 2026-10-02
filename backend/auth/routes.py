from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import User
from auth.schemas import LoginData, RegisterData, Token, UserOut
from core.security import create_token, current_user, hash_password, verify_password

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
