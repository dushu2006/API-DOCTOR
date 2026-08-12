from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select

from app.auth.schemas import ChangePasswordRequest, RegisterRequest, UpdateProfileRequest, UserResponse
from app.auth.security import hash_password, new_session_token, verify_password
from app.db.base import session_scope
from app.db.models import SessionRecord, UserRecord


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _calc_age(dob_str: str | None) -> int | None:
    if not dob_str:
        return None
    try:
        dt = datetime.strptime(dob_str.strip(), "%Y-%m-%d")
        today = datetime.now()
        age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
        return age if age >= 0 else None
    except Exception:
        return None


def _user_response(row: UserRecord) -> UserResponse:
    return UserResponse(
        id=row.id,
        email=row.email,
        username=row.username,
        full_name=row.full_name or "",
        gender=row.gender or "",
        date_of_birth=getattr(row, "date_of_birth", "") or "",
        age=row.age,
        avatar_data=row.avatar_data or "",
        current_project_id=row.current_project_id,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


class AuthStore:
    session_days = 30

    def register(self, payload: RegisterRequest) -> tuple[UserResponse, str]:
        with session_scope() as session:
            existing = session.execute(
                select(UserRecord).where(
                    or_(UserRecord.email == payload.email.lower(), UserRecord.username == payload.username.strip())
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError("An account with that email or username already exists.")

            now = _utcnow()
            dob = (payload.date_of_birth or "").strip()
            age_val = payload.age if payload.age is not None else _calc_age(dob)
            row = UserRecord(
                email=payload.email.lower(),
                username=payload.username.strip(),
                password_hash=hash_password(payload.password),
                full_name=payload.full_name.strip(),
                gender=payload.gender.strip(),
                date_of_birth=dob,
                age=age_val,
                avatar_data=payload.avatar_data or "",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            token = self._create_session(session, row.id)
            session.refresh(row)
            return _user_response(row), token

    def login(self, identifier: str, password: str) -> tuple[UserResponse, str]:
        normalized = identifier.strip().lower()
        with session_scope() as session:
            row = session.execute(
                select(UserRecord).where(
                    or_(UserRecord.email == normalized, UserRecord.username == identifier.strip())
                )
            ).scalar_one_or_none()
            if not row or not verify_password(password, row.password_hash):
                raise ValueError("Invalid email/username or password.")
            token = self._create_session(session, row.id)
            return _user_response(row), token

    def _create_session(self, session, user_id: str) -> str:
        token = new_session_token()
        now = _utcnow()
        record = SessionRecord(
            token=token,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=self.session_days),
            revoked=False,
        )
        session.add(record)
        return token

    def get_user_by_token(self, token: str | None) -> Optional[UserResponse]:
        if not token:
            return None
        now = _utcnow()
        with session_scope() as session:
            row = session.execute(
                select(UserRecord)
                .join(SessionRecord, SessionRecord.user_id == UserRecord.id)
                .where(
                    SessionRecord.token == token,
                    SessionRecord.revoked.is_(False),
                    or_(SessionRecord.expires_at.is_(None), SessionRecord.expires_at > now),
                )
            ).scalar_one_or_none()
            return _user_response(row) if row else None

    def revoke_session(self, token: str | None) -> bool:
        if not token:
            return False
        with session_scope() as session:
            row = session.execute(select(SessionRecord).where(SessionRecord.token == token)).scalar_one_or_none()
            if not row:
                return False
            row.revoked = True
            row.updated_at = _utcnow()
            session.add(row)
            return True

    def update_profile(self, user_id: str, payload: UpdateProfileRequest) -> UserResponse:
        with session_scope() as session:
            row = session.get(UserRecord, user_id)
            if not row:
                raise ValueError("User not found.")
            if payload.email and payload.email.lower() != row.email:
                existing = session.execute(select(UserRecord).where(UserRecord.email == payload.email.lower(), UserRecord.id != user_id)).scalar_one_or_none()
                if existing:
                    raise ValueError("That email is already in use.")
                row.email = payload.email.lower()
            if payload.username and payload.username.strip() != row.username:
                existing = session.execute(select(UserRecord).where(UserRecord.username == payload.username.strip(), UserRecord.id != user_id)).scalar_one_or_none()
                if existing:
                    raise ValueError("That username is already in use.")
                row.username = payload.username.strip()
            if payload.full_name is not None:
                row.full_name = payload.full_name.strip()
            if payload.gender is not None:
                row.gender = payload.gender.strip()
            if payload.date_of_birth is not None:
                row.date_of_birth = payload.date_of_birth.strip()
                calculated = _calc_age(payload.date_of_birth)
                if calculated is not None:
                    row.age = calculated
            if payload.age is not None:
                row.age = payload.age
            if payload.avatar_data is not None:
                row.avatar_data = payload.avatar_data
            row.updated_at = _utcnow()
            session.add(row)
            session.flush()
            return _user_response(row)

    def change_password(self, user_id: str, payload: ChangePasswordRequest) -> None:
        with session_scope() as session:
            row = session.get(UserRecord, user_id)
            if not row:
                raise ValueError("User not found.")
            if not verify_password(payload.current_password, row.password_hash):
                raise ValueError("Current password is incorrect.")
            row.password_hash = hash_password(payload.new_password)
            row.updated_at = _utcnow()
            session.add(row)

    def delete_account(self, user_id: str) -> None:
        with session_scope() as session:
            row = session.get(UserRecord, user_id)
            if not row:
                raise ValueError("User not found.")
            session.delete(row)


auth_store = AuthStore()
