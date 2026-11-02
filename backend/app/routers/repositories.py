from fastapi import APIRouter, Depends, HTTPException, status

from app.audit import log_operator
from app.models import (
    Package,
    PackageVersion,
    PermissionType,
    Repository,
    RepositoryAccess,
    Role,
    User,
)
from app.schemas import (
    AccessGrantCreate,
    AccessGrantOut,
    GrantUserOut,
    PackageOut,
    PackageVersionOut,
    RepositoryCreate,
    RepositoryOut,
    RepositoryUpdate,
    RoleOut,
)
from app.security import ensure_repo_permission, get_current_user, require_superadmin
from app.storage import IStorageProvider, get_storage

# Большинство операций — только суперадмин; исключения (пер-репозиторные права
# ADMIN/DELETE) объявляют зависимости сами.
router = APIRouter(prefix="/api")


@router.get("/repositories", response_model=list[RepositoryOut],
            dependencies=[Depends(require_superadmin)])
async def list_repositories():
    return await Repository.all().order_by("id")


@router.post("/repositories", response_model=RepositoryOut,
             status_code=status.HTTP_201_CREATED)
async def create_repository(
    payload: RepositoryCreate, actor: User = Depends(require_superadmin)
):
    if await Repository.exists(name=payload.name):
        raise HTTPException(status_code=409, detail="Repository name already taken")
    repo = await Repository.create(
        name=payload.name,
        type=payload.type,
        upstream_url=payload.upstream_url.rstrip("/") if payload.upstream_url else None,
        allow_overwrite=payload.allow_overwrite,
    )
    await log_operator(actor, "repository.create", f"repository {repo.name}",
                       {"type": repo.type.value, "upstream_url": repo.upstream_url})
    return repo


@router.patch("/repositories/{repo_id}", response_model=RepositoryOut)
async def update_repository(
    repo_id: int, payload: RepositoryUpdate, user: User = Depends(get_current_user)
):
    """Настройки репозитория: суперадмин или пер-репозиторное право ADMIN."""
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not user.is_superadmin:
        await ensure_repo_permission(user, repo, PermissionType.ADMIN)

    changes: dict = {}
    if payload.upstream_url is not None:
        repo.upstream_url = payload.upstream_url.rstrip("/") or None
        changes["upstream_url"] = repo.upstream_url
    if payload.allow_overwrite is not None:
        repo.allow_overwrite = payload.allow_overwrite
        changes["allow_overwrite"] = repo.allow_overwrite
    await repo.save()
    await log_operator(user, "repository.update", f"repository {repo.name}", changes)
    return repo


@router.delete("/repositories/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repo_id: int,
    actor: User = Depends(require_superadmin),
    storage: IStorageProvider = Depends(get_storage),
):
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    # Удаляем блобы, затем метаданные (пакеты и версии — каскадом)
    for pv in await PackageVersion.filter(package__repository=repo):
        await storage.delete_file(pv.storage_key)
    await repo.delete()
    await log_operator(actor, "repository.delete", f"repository {repo.name}")


# --- Назначение ролей (пользователь + роль + репозиторий) ------------------------

def _grant_out(grant: RepositoryAccess) -> AccessGrantOut:
    return AccessGrantOut(
        id=grant.id,
        user=GrantUserOut(id=grant.user.id, login=grant.user.login),
        role=RoleOut(
            id=grant.role.id, name=grant.role.name, permissions=grant.role.permissions or []
        ),
    )


@router.get("/repositories/{repo_id}/access", response_model=list[AccessGrantOut],
            dependencies=[Depends(require_superadmin)])
async def list_access(repo_id: int):
    if not await Repository.exists(id=repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    grants = (
        await RepositoryAccess.filter(repository_id=repo_id)
        .prefetch_related("user", "role")
        .order_by("id")
    )
    return [_grant_out(g) for g in grants]


@router.post("/repositories/{repo_id}/access", response_model=AccessGrantOut,
             status_code=status.HTTP_201_CREATED)
async def create_access(
    repo_id: int, payload: AccessGrantCreate, actor: User = Depends(require_superadmin)
):
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    user = await User.get_or_none(id=payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    role = await Role.get_or_none(id=payload.role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if await RepositoryAccess.exists(repository=repo, user=user, role=role):
        raise HTTPException(status_code=409, detail="Grant already exists")
    grant = await RepositoryAccess.create(repository=repo, user=user, role=role)
    await grant.fetch_related("user", "role")
    await log_operator(actor, "grant.create",
                       f"user {user.login} + role {role.name} on {repo.name}")
    return _grant_out(grant)


@router.delete("/access/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access(grant_id: int, actor: User = Depends(require_superadmin)):
    grant = await RepositoryAccess.get_or_none(id=grant_id).prefetch_related(
        "user", "role", "repository"
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await grant.delete()
    await log_operator(
        actor, "grant.revoke",
        f"user {grant.user.login} + role {grant.role.name} on {grant.repository.name}",
    )


# --- Пакеты ----------------------------------------------------------------------

@router.get("/repositories/{repo_id}/packages", response_model=list[PackageOut],
            dependencies=[Depends(require_superadmin)])
async def list_packages(repo_id: int):
    if not await Repository.exists(id=repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    packages = (
        await Package.filter(repository_id=repo_id).prefetch_related("versions").order_by("name")
    )
    return [
        PackageOut(
            id=pkg.id,
            name=pkg.name,
            dist_tags=pkg.dist_tags or {},
            versions=[
                PackageVersionOut(
                    id=pv.id,
                    version=pv.version,
                    description=pv.description,
                    dependencies=pv.dependencies or {},
                    size=pv.size,
                    shasum=pv.shasum,
                    created_at=pv.created_at,
                )
                for pv in sorted(pkg.versions, key=lambda v: v.created_at)
            ],
        )
        for pkg in packages
    ]


@router.delete("/package-versions/{pv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package_version(
    pv_id: int,
    user: User = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage),
):
    """Удаление версии: суперадмин или право DELETE на репозиторий."""
    pv = await PackageVersion.get_or_none(id=pv_id).prefetch_related("package__repository")
    if pv is None:
        raise HTTPException(status_code=404, detail="Package version not found")
    repo = pv.package.repository
    if not user.is_superadmin:
        await ensure_repo_permission(user, repo, PermissionType.DELETE)

    await storage.delete_file(pv.storage_key)
    await pv.delete()
    # Пакет без единой версии не имеет смысла — убираем
    if not await PackageVersion.exists(package=pv.package):
        await pv.package.delete()
    await log_operator(
        user, "version.delete",
        f"{pv.package.name}@{pv.version} in {repo.name}",
    )
