from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config import get_settings
from app.models import AccessType, Permission, Repository, RepoType, User

ADMIN_ROLE = "ADMIN"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# --- Пароли -----------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# --- JWT ---------------------------------------------------------------------

def create_access_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user.id),
        "login": user.login,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error

    user = await User.get_or_none(id=user_id).prefetch_related("roles")
    if user is None or not user.is_active:
        raise credentials_error
    return user


# --- RBAC --------------------------------------------------------------------

def is_admin(user: User) -> bool:
    return any(role.name == ADMIN_ROLE for role in user.roles)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_repo_access(access: AccessType, repo_type: RepoType | None = None):
    """Фабрика зависимостей: проверяет право access у пользователя на {repo_name}.

    ADMIN имеет полный доступ ко всем репозиториям. Остальным нужна запись
    Permission (роль пользователя + репозиторий + тип доступа) в БД.
    """

    async def dependency(repo_name: str, user: User = Depends(get_current_user)) -> Repository:
        repo = await Repository.get_or_none(name=repo_name)
        if repo is None or (repo_type is not None and repo.type != repo_type):
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")

        if is_admin(user):
            return repo

        allowed = await Permission.filter(
            repository=repo, access_type=access, role__users__id=user.id
        ).exists()
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{access.value} access to '{repo_name}' denied",
            )
        return repo

    return dependency
