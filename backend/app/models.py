import uuid
from enum import Enum

from tortoise import fields, models


class RepoType(str, Enum):
    HOSTED = "hosted"
    PROXY = "proxy"


class QuarantineStatus(str, Enum):
    UNKNOWN = "UNKNOWN"          # ещё не сканировался (выдаётся)
    CLEAN = "CLEAN"              # проверен, угроз нет
    QUARANTINED = "QUARANTINED"  # угроза найдена, выдача заблокирована
    WHITELISTED = "WHITELISTED"  # ручное исключение, сканер игнорирует


class PermissionType(str, Enum):
    """Атомарные права над репозиторием."""

    CREATE = "CREATE"  # загрузка новых версий (publish)
    READ = "READ"      # скачивание артефактов и метаданных версий
    UPDATE = "UPDATE"  # перезапись существующих версий (если разрешено политикой репозитория)
    DELETE = "DELETE"  # удаление версий/пакетов
    LIST = "LIST"      # поиск и списки пакетов
    ADMIN = "ADMIN"    # изменение параметров репозитория


class User(models.Model):
    id = fields.IntField(pk=True)
    login = fields.CharField(max_length=64, unique=True)
    hashed_password = fields.CharField(max_length=128)
    is_active = fields.BooleanField(default=True)
    # Глобальный суперадмин: полный доступ ко всему + управление юзерами/ролями/репозиториями
    is_superadmin = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"


class Role(models.Model):
    """Именованный набор атомарных прав (например, developer, ci_runner, repo_admin).

    Сама по себе роль прав не даёт — она действует только будучи назначенной
    пользователю в контексте репозитория (RepositoryAccess).
    """

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True)
    # Список значений PermissionType, например ["READ", "LIST", "CREATE"]
    permissions = fields.JSONField(default=list)

    class Meta:
        table = "roles"

    def __str__(self) -> str:
        return self.name


class Repository(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True)
    type = fields.CharEnumField(RepoType, max_length=16)
    # Обязателен только для proxy-репозиториев
    upstream_url = fields.CharField(max_length=512, null=True)
    # Политика: можно ли перезаписывать существующие версии (требует права UPDATE)
    allow_overwrite = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "repositories"


class RepositoryAccess(models.Model):
    """Назначение роли пользователю в контексте репозитория.

    У пользователя может быть несколько ролей на один репозиторий —
    права суммируются.
    """

    id = fields.IntField(pk=True)
    user: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="repository_access", on_delete=fields.CASCADE
    )
    repository: fields.ForeignKeyRelation[Repository] = fields.ForeignKeyField(
        "models.Repository", related_name="access_grants", on_delete=fields.CASCADE
    )
    role: fields.ForeignKeyRelation[Role] = fields.ForeignKeyField(
        "models.Role", related_name="grants", on_delete=fields.CASCADE
    )

    class Meta:
        table = "repository_access"
        unique_together = (("user", "repository", "role"),)


class Package(models.Model):
    """npm-пакет внутри репозитория (hosted — опубликован, proxy — закэширован)."""

    id = fields.IntField(pk=True)
    repository: fields.ForeignKeyRelation[Repository] = fields.ForeignKeyField(
        "models.Repository", related_name="packages", on_delete=fields.CASCADE
    )
    # Полное имя, включая scope: "lodash" или "@acme/utils"
    name = fields.CharField(max_length=214)
    dist_tags = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    versions: fields.ReverseRelation["PackageVersion"]

    class Meta:
        table = "packages"
        unique_together = (("repository", "name"),)


class WhitelistRule(models.Model):
    """Ручное исключение из карантина: точная пара пакет+версия.

    Создание правила переводит совпадающие версии (во всех репозиториях)
    в WHITELISTED; сканер такие версии игнорирует.
    """

    id = fields.IntField(pk=True)
    package_name = fields.CharField(max_length=214)
    version = fields.CharField(max_length=64)
    reason = fields.TextField()
    created_by: fields.ForeignKeyNullableRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="whitelist_rules", null=True, on_delete=fields.SET_NULL
    )
    created_by_login = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "whitelist_rules"
        unique_together = (("package_name", "version"),)


class DownloadAuditLog(models.Model):
    """Аудит выдачи: каждый успешный факт скачивания пакета клиентом.

    user/repository — SET_NULL, чтобы удаление пользователя или репозитория
    не стирало историю; логин и имя дублируются строками.
    """

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    user: fields.ForeignKeyNullableRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="downloads", null=True, on_delete=fields.SET_NULL
    )
    user_login = fields.CharField(max_length=64)
    repository: fields.ForeignKeyNullableRelation[Repository] = fields.ForeignKeyField(
        "models.Repository", related_name="downloads", null=True, on_delete=fields.SET_NULL
    )
    repository_name = fields.CharField(max_length=64)
    package_name = fields.CharField(max_length=214)
    package_version = fields.CharField(max_length=64)
    downloaded_at = fields.DatetimeField(auto_now_add=True)
    user_agent = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "download_audit_log"
        ordering = ["-downloaded_at"]


class OperatorAuditLog(models.Model):
    """Аудит действий операторов: управление юзерами/ролями/репозиториями,
    удаление версий; позже — карантинные решения (смена статуса, whitelist)."""

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    actor: fields.ForeignKeyNullableRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="operator_actions", null=True, on_delete=fields.SET_NULL
    )
    actor_login = fields.CharField(max_length=64)
    action = fields.CharField(max_length=64)   # например "user.create", "grant.revoke"
    target = fields.CharField(max_length=512)  # человекочитаемая цель действия
    details = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "operator_audit_log"
        ordering = ["-created_at"]


class PackageVersion(models.Model):
    """Версия пакета; tgz-блоб лежит в IStorageProvider под storage_key."""

    id = fields.IntField(pk=True)
    package: fields.ForeignKeyRelation[Package] = fields.ForeignKeyField(
        "models.Package", related_name="versions", on_delete=fields.CASCADE
    )
    version = fields.CharField(max_length=64)
    description = fields.TextField(null=True)
    # Извлечённые зависимости: {"lodash": "^4.17.21", ...}
    dependencies = fields.JSONField(default=dict)
    # Полный манифест версии (package.json / versions[v] из publish-запроса)
    manifest = fields.JSONField(default=dict)
    filename = fields.CharField(max_length=300)
    storage_key = fields.CharField(max_length=1200)
    size = fields.BigIntField()
    shasum = fields.CharField(max_length=40, null=True)      # sha1 (npm dist.shasum)
    integrity = fields.CharField(max_length=128, null=True)  # sha512-<base64>
    quarantine_status = fields.CharEnumField(
        QuarantineStatus, max_length=16, default=QuarantineStatus.UNKNOWN
    )
    uploaded_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="published_versions", null=True, on_delete=fields.SET_NULL
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "package_versions"
        unique_together = (("package", "version"),)
