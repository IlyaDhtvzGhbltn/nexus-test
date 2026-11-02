from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config import get_settings
from app.models import PermissionType, Repository, RepositoryAccess, RepoType, User

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

    user = await User.get_or_none(id=user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


# --- RBAC --------------------------------------------------------------------

async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    return user


async def get_repo_permissions(user: User, repo: Repository) -> set[str]:
    """Суммарный набор прав пользователя на репозиторий (объединение всех его ролей)."""
    if user.is_superadmin:
        return {p.value for p in PermissionType}
    grants = await RepositoryAccess.filter(user=user, repository=repo).prefetch_related("role")
    permissions: set[str] = set()
    for grant in grants:
        permissions.update(grant.role.permissions or [])
    return permissions


async def ensure_repo_permission(
    user: User, repo: Repository, permission: PermissionType
) -> None:
    if permission.value not in await get_repo_permissions(user, repo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{permission.value} access to '{repo.name}' denied",
        )


def get_repository(repo_type: RepoType | None = None):
    """Зависимость: находит репозиторий {repo_name} без проверки прав."""

    async def dependency(repo_name: str) -> Repository:
        repo = await Repository.get_or_none(name=repo_name)
        if repo is None or (repo_type is not None and repo.type != repo_type):
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")
        return repo

    return dependency


def require_repo_access(permission: PermissionType, repo_type: RepoType | None = None):
    """Зависимость: репозиторий {repo_name} + проверка атомарного права у пользователя."""

    async def dependency(
        repo_name: str, user: User = Depends(get_current_user)
    ) -> Repository:
        repo = await Repository.get_or_none(name=repo_name)
        if repo is None or (repo_type is not None and repo.type != repo_type):
            raise HTTPException(status_code=404, detail=f"Repository '{repo_name}' not found")
        await ensure_repo_permission(user, repo, permission)
        return repo

    return dependency
