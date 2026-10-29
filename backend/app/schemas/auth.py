from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.security import normalize_email, validate_password
from app.schemas.user import UserResponse


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    password: str
    confirm_password: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank")
        return cleaned

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        return validate_password(value)

    @model_validator(mode="after")
    def passwords_match(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)


class AuthResponse(BaseModel):
    user: UserResponse
