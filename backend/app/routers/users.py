from fastapi import APIRouter, Depends, HTTPException, status

from app.audit import log_operator
from app.models import Role, User
from app.schemas import RoleCreate, RoleOut, RoleUpdate, UserCreate, UserOut, UserUpdate
from app.security import hash_password, require_superadmin

router = APIRouter(prefix="/api", dependencies=[Depends(require_superadmin)])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        login=user.login,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        created_at=user.created_at,
    )


async def _other_active_superadmin_exists(except_user_id: int) -> bool:
    return await User.filter(is_superadmin=True, is_active=True).exclude(
        id=except_user_id
    ).exists()


# --- Users --------------------------------------------------------------------

@router.get("/users", response_model=list[UserOut])
async def list_users():
    return [_user_out(u) for u in await User.all().order_by("id")]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, actor: User = Depends(require_superadmin)):
    if await User.exists(login=payload.login):
        raise HTTPException(status_code=409, detail="Login already taken")
    user = await User.create(
        login=payload.login,
        hashed_password=hash_password(payload.password),
        is_superadmin=payload.is_superadmin,
    )
    await log_operator(actor, "user.create", f"user {user.login}",
                       {"is_superadmin": user.is_superadmin})
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: UserUpdate, current: User = Depends(require_superadmin)
):
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Защита от самострела
    if user.id == current.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    if user.id == current.id and payload.is_superadmin is False:
        raise HTTPException(status_code=400, detail="Cannot revoke your own superadmin")
    # В системе всегда должен оставаться хотя бы один активный суперадмин
    if (
        user.is_superadmin
        and (payload.is_active is False or payload.is_superadmin is False)
        and not await _other_active_superadmin_exists(user.id)
    ):
        raise HTTPException(status_code=400, detail="Cannot remove the last active superadmin")

    changes: dict = {}
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
        changes["password"] = "changed"
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
    if payload.is_superadmin is not None:
        user.is_superadmin = payload.is_superadmin
        changes["is_superadmin"] = payload.is_superadmin
    await user.save()
    await log_operator(current, "user.update", f"user {user.login}", changes)
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current: User = Depends(require_superadmin)):
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if (
        user.is_superadmin
        and user.is_active
        and not await _other_active_superadmin_exists(user.id)
    ):
        raise HTTPException(status_code=400, detail="Cannot delete the last active superadmin")
    await user.delete()
    await log_operator(current, "user.delete", f"user {user.login}")


# --- Roles --------------------------------------------------------------------

def _role_out(role: Role) -> RoleOut:
    return RoleOut(id=role.id, name=role.name, permissions=role.permissions or [])


@router.get("/roles", response_model=list[RoleOut])
async def list_roles():
    return [_role_out(r) for r in await Role.all().order_by("id")]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, actor: User = Depends(require_superadmin)):
    name = payload.name.strip()
    if await Role.exists(name=name):
        raise HTTPException(status_code=409, detail="Role already exists")
    role = await Role.create(
        name=name, permissions=sorted({p.value for p in payload.permissions})
    )
    await log_operator(actor, "role.create", f"role {role.name}",
                       {"permissions": role.permissions})
    return _role_out(role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: int, payload: RoleUpdate, actor: User = Depends(require_superadmin)
):
    role = await Role.get_or_none(id=role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if payload.permissions is not None:
        role.permissions = sorted({p.value for p in payload.permissions})
        await role.save()
        await log_operator(actor, "role.update", f"role {role.name}",
                           {"permissions": role.permissions})
    return _role_out(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: int, actor: User = Depends(require_superadmin)):
    role = await Role.get_or_none(id=role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    # Каскадом удаляются все назначения этой роли (RepositoryAccess)
    await role.delete()
    await log_operator(actor, "role.delete", f"role {role.name}")
