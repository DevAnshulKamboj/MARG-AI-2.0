from pydantic import BaseModel, EmailStr, Field


class RegisterData(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginData(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    model_config = {"from_attributes": True}
