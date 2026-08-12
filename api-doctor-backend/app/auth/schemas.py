from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str = ""
    gender: str = ""
    date_of_birth: str = ""
    age: int | None = None
    avatar_data: str = ""
    current_project_id: str | None = None
    created_at: str
    updated_at: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=200)
    full_name: str = ""
    gender: str = ""
    date_of_birth: str = ""
    age: int | None = Field(default=None, ge=1, le=150)
    avatar_data: str = ""


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=200)


class UpdateProfileRequest(BaseModel):
    email: str | None = Field(default=None, min_length=5, max_length=255)
    username: str | None = Field(default=None, min_length=3, max_length=50)
    full_name: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None
    age: int | None = Field(default=None, ge=1, le=150)
    avatar_data: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=6, max_length=200)
    new_password: str = Field(min_length=6, max_length=200)


class AuthResponse(BaseModel):
    user: UserResponse
    session_token: str


class MessageResponse(BaseModel):
    status: str = "ok"
    message: str = ""
