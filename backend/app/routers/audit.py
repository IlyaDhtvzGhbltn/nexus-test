from fastapi import APIRouter, Depends

from app.models import DownloadAuditLog, OperatorAuditLog
from app.schemas import DownloadLogOut, OperatorLogOut
from app.security import require_superadmin

router = APIRouter(prefix="/api/audit", dependencies=[Depends(require_superadmin)])

MAX_PAGE = 500


@router.get("/downloads", response_model=list[DownloadLogOut])
async def list_downloads(
    package: str | None = None,
    user: str | None = None,
    repository: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Журнал выдачи пакетов: кто, что и когда скачал."""
    query = DownloadAuditLog.all()
    if package:
        query = query.filter(package_name__icontains=package)
    if user:
        query = query.filter(user_login__icontains=user)
    if repository:
        query = query.filter(repository_name=repository)
    rows = await query.offset(max(0, offset)).limit(max(1, min(limit, MAX_PAGE)))
    return [
        DownloadLogOut(
            id=str(r.id),
            user_login=r.user_login,
            repository_name=r.repository_name,
            package_name=r.package_name,
            package_version=r.package_version,
            downloaded_at=r.downloaded_at,
            user_agent=r.user_agent,
        )
        for r in rows
    ]


@router.get("/operations", response_model=list[OperatorLogOut])
async def list_operations(
    action: str | None = None,
    actor: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Журнал действий операторов (admin API)."""
    query = OperatorAuditLog.all()
    if action:
        query = query.filter(action__icontains=action)
    if actor:
        query = query.filter(actor_login__icontains=actor)
    rows = await query.offset(max(0, offset)).limit(max(1, min(limit, MAX_PAGE)))
    return [
        OperatorLogOut(
            id=str(r.id),
            actor_login=r.actor_login,
            action=r.action,
            target=r.target,
            details=r.details or {},
            created_at=r.created_at,
        )
        for r in rows
    ]
