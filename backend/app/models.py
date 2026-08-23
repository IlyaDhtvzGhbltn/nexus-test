from enum import Enum

from tortoise import fields, models


class RepoType(str, Enum):
    HOSTED = "hosted"
    PROXY = "proxy"


class AccessType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


class Role(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True)

    users: fields.ManyToManyRelation["User"]
    permissions: fields.ReverseRelation["Permission"]

    class Meta:
        table = "roles"

    def __str__(self) -> str:
        return self.name


class User(models.Model):
    id = fields.IntField(pk=True)
    login = fields.CharField(max_length=64, unique=True)
    hashed_password = fields.CharField(max_length=128)
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    roles: fields.ManyToManyRelation[Role] = fields.ManyToManyField(
        "models.Role", related_name="users", through="user_roles"
    )

    class Meta:
        table = "users"


class Repository(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True)
    type = fields.CharEnumField(RepoType, max_length=16)
    # Обязателен только для proxy-репозиториев
    upstream_url = fields.CharField(max_length=512, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    permissions: fields.ReverseRelation["Permission"]
    artifacts: fields.ReverseRelation["Artifact"]

    class Meta:
        table = "repositories"


class Permission(models.Model):
    """Связка Роль + Репозиторий + Тип доступа."""

    id = fields.IntField(pk=True)
    role: fields.ForeignKeyRelation[Role] = fields.ForeignKeyField(
        "models.Role", related_name="permissions", on_delete=fields.CASCADE
    )
    repository: fields.ForeignKeyRelation[Repository] = fields.ForeignKeyField(
        "models.Repository", related_name="permissions", on_delete=fields.CASCADE
    )
    access_type = fields.CharEnumField(AccessType, max_length=8)

    class Meta:
        table = "permissions"
        unique_together = (("role", "repository", "access_type"),)


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
    uploaded_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="published_versions", null=True, on_delete=fields.SET_NULL
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "package_versions"
        unique_together = (("package", "version"),)
