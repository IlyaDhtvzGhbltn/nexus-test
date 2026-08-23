from fastapi import APIRouter, Depends, HTTPException, status

from app.models import Package, PackageVersion, Permission, Repository, Role
from app.schemas import (
    PackageOut,
    PackageVersionOut,
    PermissionCreate,
    PermissionOut,
    RepositoryCreate,
    RepositoryOut,
    RepositoryUpdate,
    RoleOut,
)
from app.security import require_admin
from app.storage import IStorageProvider, get_storage

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


@router.get("/repositories", response_model=list[RepositoryOut])
async def list_repositories():
    return await Repository.all().order_by("id")


@router.post("/repositories", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def create_repository(payload: RepositoryCreate):
    if await Repository.exists(name=payload.name):
        raise HTTPException(status_code=409, detail="Repository name already taken")
    return await Repository.create(
        name=payload.name,
        type=payload.type,
        upstream_url=payload.upstream_url.rstrip("/") if payload.upstream_url else None,
    )


@router.patch("/repositories/{repo_id}", response_model=RepositoryOut)
async def update_repository(repo_id: int, payload: RepositoryUpdate):
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if payload.upstream_url is not None:
        repo.upstream_url = payload.upstream_url.rstrip("/") or None
        await repo.save()
    return repo


@router.delete("/repositories/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(repo_id: int, storage: IStorageProvider = Depends(get_storage)):
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    # Удаляем блобы, затем метаданные (пакеты и версии — каскадом)
    for pv in await PackageVersion.filter(package__repository=repo):
        await storage.delete_file(pv.storage_key)
    await repo.delete()


@router.get("/repositories/{repo_id}/packages", response_model=list[PackageOut])
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


# --- Permissions ---------------------------------------------------------------

def _perm_out(perm: Permission) -> PermissionOut:
    return PermissionOut(
        id=perm.id,
        role=RoleOut(id=perm.role.id, name=perm.role.name),
        access_type=perm.access_type,
    )


@router.get("/repositories/{repo_id}/permissions", response_model=list[PermissionOut])
async def list_permissions(repo_id: int):
    if not await Repository.exists(id=repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    perms = await Permission.filter(repository_id=repo_id).prefetch_related("role").order_by("id")
    return [_perm_out(p) for p in perms]


@router.post(
    "/repositories/{repo_id}/permissions",
    response_model=PermissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_permission(repo_id: int, payload: PermissionCreate):
    repo = await Repository.get_or_none(id=repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    role = await Role.get_or_none(id=payload.role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if await Permission.exists(repository=repo, role=role, access_type=payload.access_type):
        raise HTTPException(status_code=409, detail="Permission already exists")
    perm = await Permission.create(repository=repo, role=role, access_type=payload.access_type)
    await perm.fetch_related("role")
    return _perm_out(perm)


@router.delete("/permissions/{perm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(perm_id: int):
    deleted = await Permission.filter(id=perm_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Permission not found")
