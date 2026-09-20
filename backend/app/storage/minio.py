"""MinioStorageProvider — общее блоб-хранилище через S3 API (MinIO/S3-совместимое).

Реализует тот же IStorageProvider, что и LocalStorageProvider, поэтому
бизнес-логика не меняется. Загрузка идёт потоково через multipart upload:
файл никогда не собирается в памяти целиком, а недокачанные загрузки
не становятся видимыми (multipart завершается только последним байтом).
"""

import asyncio
import hashlib
from typing import AsyncIterator

import aioboto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.storage.base import IStorageProvider, StoredBlob

# S3 требует части multipart-загрузки минимум 5 MiB (кроме последней)
PART_SIZE = 8 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def _is_not_found(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code", "")) in _NOT_FOUND_CODES


class MinioStorageProvider(IStorageProvider):
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._session = aioboto3.Session()
        self._bucket_ready = False
        self._bucket_lock = asyncio.Lock()

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            # MinIO ожидает path-style адресацию (bucket в пути, не в hostname)
            config=BotoConfig(s3={"addressing_style": "path"}),
        )

    async def _ensure_bucket(self, s3) -> None:
        if self._bucket_ready:
            return
        async with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError:
                try:
                    await s3.create_bucket(Bucket=self._bucket)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    # Параллельная нода могла создать бакет первой
                    if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                        raise
            self._bucket_ready = True

    async def upload_file(self, key: str, stream: AsyncIterator[bytes]) -> StoredBlob:
        digest = hashlib.sha256()
        size = 0
        buffer = bytearray()
        upload_id: str | None = None
        parts: list[dict] = []

        async with self._client() as s3:
            await self._ensure_bucket(s3)
            try:
                async for chunk in stream:
                    digest.update(chunk)
                    size += len(chunk)
                    buffer.extend(chunk)
                    if len(buffer) >= PART_SIZE:
                        if upload_id is None:
                            created = await s3.create_multipart_upload(
                                Bucket=self._bucket, Key=key
                            )
                            upload_id = created["UploadId"]
                        part = await s3.upload_part(
                            Bucket=self._bucket,
                            Key=key,
                            PartNumber=len(parts) + 1,
                            UploadId=upload_id,
                            Body=bytes(buffer),
                        )
                        parts.append({"ETag": part["ETag"], "PartNumber": len(parts) + 1})
                        buffer.clear()

                if upload_id is None:
                    # Маленький файл — одной операцией
                    await s3.put_object(Bucket=self._bucket, Key=key, Body=bytes(buffer))
                else:
                    if buffer:
                        part = await s3.upload_part(
                            Bucket=self._bucket,
                            Key=key,
                            PartNumber=len(parts) + 1,
                            UploadId=upload_id,
                            Body=bytes(buffer),
                        )
                        parts.append({"ETag": part["ETag"], "PartNumber": len(parts) + 1})
                    await s3.complete_multipart_upload(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )
            except BaseException:  # включая CancelledError — обрыв отменяет multipart
                if upload_id is not None:
                    try:
                        await s3.abort_multipart_upload(
                            Bucket=self._bucket, Key=key, UploadId=upload_id
                        )
                    except ClientError:
                        pass
                raise

        return StoredBlob(key=key, size=size, sha256=digest.hexdigest())

    async def download_file(self, key: str) -> AsyncIterator[bytes]:
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            try:
                obj = await s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    raise FileNotFoundError(key) from exc
                raise
            body = obj["Body"]
            while chunk := await body.read(DOWNLOAD_CHUNK):
                yield chunk

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                if _is_not_found(exc):
                    return False
                raise

    async def delete_file(self, key: str) -> None:
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            # delete_object идемпотентен: отсутствие ключа — не ошибка
            await s3.delete_object(Bucket=self._bucket, Key=key)
