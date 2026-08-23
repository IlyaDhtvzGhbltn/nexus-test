from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import AccessType, RepoType


# --- Auth ---------------------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Roles --------------------------------------------------------------------

class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class RoleOut(BaseModel):
    id: int
    name: str


# --- Users --------------------------------------------------------------------

class UserCreate(BaseModel):
    login: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=128)
    is_active: bool | None = None
    role_ids: list[int] | None = None


class UserOut(BaseModel):
    id: int
    login: str
    is_active: bool
    created_at: datetime
    roles: list[RoleOut]


# --- Repositories ---------------------------------------------------------------

class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    type: RepoType
    upstream_url: str | None = None

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


class RepositoryOut(BaseModel):
    id: int
    name: str
    type: RepoType
    upstream_url: str | None
    created_at: datetime


# --- Permissions -----------------------------------------------------------------

class PermissionCreate(BaseModel):
    role_id: int
    access_type: AccessType


class PermissionOut(BaseModel):
    id: int
    role: RoleOut
    access_type: AccessType


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
