from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.security import normalize_email, validate_password


class EmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)


class VerifyOtpRequest(EmailRequest):
    code: str = Field(pattern=r"^\d{6}$")


class ResetPasswordRequest(BaseModel):
    reset_grant: str = Field(min_length=32, max_length=256)
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        return validate_password(value)

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class ResetGrantResponse(BaseModel):
    reset_grant: str


class GenericOtpResponse(BaseModel):
    message: str
