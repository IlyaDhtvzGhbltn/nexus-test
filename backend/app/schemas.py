from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import PermissionType, RepoType


# --- Auth ---------------------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Roles --------------------------------------------------------------------

class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    permissions: list[PermissionType] = []


class RoleUpdate(BaseModel):
    permissions: list[PermissionType] | None = None


class RoleOut(BaseModel):
    id: int
    name: str
    permissions: list[PermissionType]


# --- Users --------------------------------------------------------------------

class UserCreate(BaseModel):
    login: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    is_superadmin: bool = False


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=128)
    is_active: bool | None = None
    is_superadmin: bool | None = None


class UserOut(BaseModel):
    id: int
    login: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime


# --- Назначение ролей на репозиторий --------------------------------------------

class AccessGrantCreate(BaseModel):
    user_id: int
    role_id: int


class GrantUserOut(BaseModel):
    id: int
    login: str


class AccessGrantOut(BaseModel):
    id: int
    user: GrantUserOut
    role: RoleOut


# --- Repositories ---------------------------------------------------------------

class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    type: RepoType
    upstream_url: str | None = None
    allow_overwrite: bool = False

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream(cls, v: str | None, info):
        if info.data.get("type") == RepoType.PROXY and not v:
            raise ValueError("upstream_url is required for proxy repositories")
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("upstream_url must start with http:// or https://")
        return v


class RepositoryUpdate(BaseModel):
    upstream_url: str | None = None
    allow_overwrite: bool | None = None


class RepositoryOut(BaseModel):
    id: int
    name: str
    type: RepoType
    upstream_url: str | None
    allow_overwrite: bool
    created_at: datetime


# --- Аудит ----------------------------------------------------------------------

class DownloadLogOut(BaseModel):
    id: str
    user_login: str
    repository_name: str
    package_name: str
    package_version: str
    downloaded_at: datetime
    user_agent: str | None


class OperatorLogOut(BaseModel):
    id: str
    actor_login: str
    action: str
    target: str
    details: dict
    created_at: datetime


# --- Packages (npm) ---------------------------------------------------------------

class PackageVersionOut(BaseModel):
    id: int
    version: str
    description: str | None
    dependencies: dict[str, str]
    size: int
    shasum: str | None
    created_at: datetime


class PackageOut(BaseModel):
    id: int
    name: str
    dist_tags: dict[str, str]
    versions: list[PackageVersionOut]
