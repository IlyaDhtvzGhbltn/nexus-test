"""Раздел ИБ-инженера: статусы карантина, whitelist.

Пока доступ — суперадмин; при появлении выделенной роли ИБ достаточно
заменить зависимость.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.audit import log_operator
from app.models import PackageVersion, QuarantineStatus, User, WhitelistRule
from app.schemas import (
    QuarantineStatusUpdate,
    SecurityVersionOut,
    WhitelistCreate,
    WhitelistOut,
)
from app.security import require_superadmin

router = APIRouter(prefix="/api/security", dependencies=[Depends(require_superadmin)])

MAX_PAGE = 500


def _version_out(pv: PackageVersion) -> SecurityVersionOut:
    return SecurityVersionOut(
        id=pv.id,
        repository_name=pv.package.repository.name,
        package_name=pv.package.name,
        version=pv.version,
        quarantine_status=pv.quarantine_status,
        size=pv.size,
        created_at=pv.created_at,
    )


@router.get("/versions", response_model=list[SecurityVersionOut])
async def list_versions(
    status_filter: QuarantineStatus | None = None,
    package: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = PackageVersion.all().prefetch_related("package__repository")
    if status_filter is not None:
        query = query.filter(quarantine_status=status_filter)
    if package:
        query = query.filter(package__name__icontains=package)
    rows = await query.order_by("-created_at").offset(max(0, offset)).limit(
        max(1, min(limit, MAX_PAGE))
    )
    return [_version_out(pv) for pv in rows]


@router.post("/versions/{pv_id}/status", response_model=SecurityVersionOut)
async def set_status(
    pv_id: int, payload: QuarantineStatusUpdate, actor: User = Depends(require_superadmin)
):
    """Ручная смена статуса (например, CLEAN после ложного срабатывания)."""
    pv = await PackageVersion.get_or_none(id=pv_id).prefetch_related("package__repository")
    if pv is None:
        raise HTTPException(status_code=404, detail="Package version not found")
    if pv.quarantine_status == QuarantineStatus.WHITELISTED:
        raise HTTPException(
            status_code=400,
            detail="Version is whitelisted — remove the whitelist rule first",
        )
    old_status = pv.quarantine_status
    pv.quarantine_status = payload.status
    await pv.save()
    await log_operator(
        actor,
        "quarantine.status_change",
        f"{pv.package.name}@{pv.version} in {pv.package.repository.name}",
        {"from": old_status.value, "to": payload.status.value},
    )
    return _version_out(pv)


# --- Whitelist -------------------------------------------------------------------

def _whitelist_out(rule: WhitelistRule) -> WhitelistOut:
    return WhitelistOut(
        id=rule.id,
        package_name=rule.package_name,
        version=rule.version,
        reason=rule.reason,
        created_by_login=rule.created_by_login,
        created_at=rule.created_at,
    )


@router.get("/whitelist", response_model=list[WhitelistOut])
async def list_whitelist():
    return [_whitelist_out(r) for r in await WhitelistRule.all().order_by("-created_at")]


@router.post("/whitelist", response_model=WhitelistOut, status_code=status.HTTP_201_CREATED)
async def create_whitelist_rule(
    payload: WhitelistCreate, actor: User = Depends(require_superadmin)
):
    if await WhitelistRule.exists(package_name=payload.package_name, version=payload.version):
        raise HTTPException(status_code=409, detail="Whitelist rule already exists")
    rule = await WhitelistRule.create(
        package_name=payload.package_name,
        version=payload.version,
        reason=payload.reason,
        created_by=actor,
        created_by_login=actor.login,
    )
    # Все совпадающие версии (во всех репозиториях) — в WHITELISTED.
    # UPDATE с join-фильтром не везде поддержан — обновляем по списку id.
    ids = await PackageVersion.filter(
        package__name=payload.package_name, version=payload.version
    ).values_list("id", flat=True)
    updated = 0
    if ids:
        updated = await PackageVersion.filter(id__in=ids).update(
            quarantine_status=QuarantineStatus.WHITELISTED
        )
    await log_operator(
        actor,
        "whitelist.add",
        f"{payload.package_name}@{payload.version}",
        {"reason": payload.reason, "versions_updated": updated},
    )
    return _whitelist_out(rule)


@router.delete("/whitelist/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_whitelist_rule(rule_id: int, actor: User = Depends(require_superadmin)):
    rule = await WhitelistRule.get_or_none(id=rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Whitelist rule not found")
    await rule.delete()
    # Версии возвращаются в UNKNOWN — при следующем обходе сканер проверит заново
    ids = await PackageVersion.filter(
        package__name=rule.package_name,
        version=rule.version,
        quarantine_status=QuarantineStatus.WHITELISTED,
    ).values_list("id", flat=True)
    if ids:
        await PackageVersion.filter(id__in=ids).update(
            quarantine_status=QuarantineStatus.UNKNOWN
        )
    await log_operator(actor, "whitelist.remove", f"{rule.package_name}@{rule.version}")
