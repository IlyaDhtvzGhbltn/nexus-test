from fastapi import APIRouter, Depends, HTTPException, status

from app.models import Role, User
from app.schemas import RoleCreate, RoleOut, UserCreate, UserOut, UserUpdate
from app.security import ADMIN_ROLE, hash_password, require_admin

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        login=user.login,
        is_active=user.is_active,
        created_at=user.created_at,
        roles=[RoleOut(id=r.id, name=r.name) for r in user.roles],
    )


async def _resolve_roles(role_ids: list[int]) -> list[Role]:
    roles = await Role.filter(id__in=role_ids)
    if len(roles) != len(set(role_ids)):
        raise HTTPException(status_code=400, detail="Unknown role id")
    return roles


@router.get("/roles", response_model=list[RoleOut])
async def list_roles():
    return [RoleOut(id=r.id, name=r.name) for r in await Role.all().order_by("id")]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate):
    name = payload.name.strip()
    if await Role.exists(name=name):
        raise HTTPException(status_code=409, detail="Role already exists")
    role = await Role.create(name=name)
    return RoleOut(id=role.id, name=role.name)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: int):
    role = await Role.get_or_none(id=role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.name == ADMIN_ROLE:
        raise HTTPException(status_code=400, detail="Cannot delete the ADMIN role")
    # Каскадом удаляются permissions роли и её привязки к пользователям
    await role.delete()


@router.get("/users", response_model=list[UserOut])
async def list_users():
    users = await User.all().prefetch_related("roles").order_by("id")
    return [_to_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate):
    if await User.exists(login=payload.login):
        raise HTTPException(status_code=409, detail="Login already taken")
    user = await User.create(login=payload.login, hashed_password=hash_password(payload.password))
    if payload.role_ids:
        await user.roles.add(*await _resolve_roles(payload.role_ids))
    await user.fetch_related("roles")
    return _to_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate):
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await user.save()

    if payload.role_ids is not None:
        await user.roles.clear()
        if payload.role_ids:
            await user.roles.add(*await _resolve_roles(payload.role_ids))

    await user.fetch_related("roles")
    return _to_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    deleted = await User.filter(id=user_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
