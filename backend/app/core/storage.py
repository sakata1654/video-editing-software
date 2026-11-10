"""
Storage abstraction layer.
Supports local filesystem (dev) and S3-compatible object storage (prod).
Switch via STORAGE_BACKEND env var without changing any other code.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import get_settings

settings = get_settings()


class StorageBackend(Protocol):
    def save_upload(self, file_obj: BinaryIO, filename: str) -> tuple[str, int]: ...
    def save_asset(self, file_obj: BinaryIO, subdir: str, filename: str) -> str: ...
    def get_output_path(self, filename: str) -> Path: ...
    def get_temp_path(self, filename: str) -> Path: ...
    def upload_output(self, local_path: Path, remote_key: str) -> str: ...
    def ensure_local(self, stored_path: str) -> Path: ...
    def absolute_to_url(self, abs_path: str) -> str: ...
    def delete_file(self, path: str) -> None: ...


class LocalStorage:
    """Stores files on the local filesystem."""

    def save_upload(self, file_obj: BinaryIO, filename: str) -> tuple[str, int]:
        dest = settings.uploads_dir / filename
        if dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            dest = settings.uploads_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

        with open(dest, "wb") as f:
            shutil.copyfileobj(file_obj, f)

        return str(dest), dest.stat().st_size

    def save_asset(self, file_obj: BinaryIO, subdir: str, filename: str) -> str:
        asset_dir = settings.storage_root / "assets" / subdir
        asset_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix
        dest = asset_dir / f"{uuid.uuid4().hex}{suffix}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(file_obj, f)
        return str(dest)

    def get_upload_path(self, filename: str) -> Path:
        return settings.uploads_dir / filename

    def get_output_path(self, filename: str) -> Path:
        p = settings.outputs_dir / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def get_temp_path(self, filename: str) -> Path:
        p = settings.temp_dir / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def upload_output(self, local_path: Path, remote_key: str) -> str:
        return str(local_path)

    def ensure_local(self, stored_path: str) -> Path:
        return Path(stored_path)

    def absolute_to_url(self, abs_path: str) -> str:
        p = Path(abs_path)
        try:
            rel = p.relative_to(settings.storage_root)
            return f"/files/{rel.as_posix()}"
        except ValueError:
            return f"/files/{p.name}"

    def delete_file(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()

    def cleanup_temp(self, path: str) -> None:
        self.delete_file(path)


class S3Storage:
    """S3-compatible object storage (AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces)."""

    def __init__(self) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError("Install boto3 for S3 storage: pip install boto3") from exc

        kwargs: dict = {"region_name": settings.s3_region}
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.client("s3", **kwargs)
        self.bucket = settings.s3_bucket

    def save_upload(self, file_obj: BinaryIO, filename: str) -> tuple[str, int]:
        key = f"uploads/{uuid.uuid4().hex}_{Path(filename).name}"
        local_tmp = self.get_temp_path(Path(key).name)
        with open(local_tmp, "wb") as f:
            shutil.copyfileobj(file_obj, f)
        size = local_tmp.stat().st_size
        self.client.upload_file(str(local_tmp), self.bucket, key)
        local_tmp.unlink(missing_ok=True)
        return f"s3://{self.bucket}/{key}", size

    def save_asset(self, file_obj: BinaryIO, subdir: str, filename: str) -> str:
        suffix = Path(filename).suffix
        key = f"assets/{subdir}/{uuid.uuid4().hex}{suffix}"
        self.client.upload_fileobj(file_obj, self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def get_output_path(self, filename: str) -> Path:
        p = settings.temp_dir / "outputs" / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def get_temp_path(self, filename: str) -> Path:
        p = settings.temp_dir / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def upload_output(self, local_path: Path, remote_key: str) -> str:
        key = f"outputs/{remote_key}"
        self.client.upload_file(str(local_path), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def ensure_local(self, stored_path: str) -> Path:
        if stored_path.startswith("s3://"):
            _, _, rest = stored_path.partition("s3://")
            _, _, key = rest.partition("/")
            local_path = self.get_temp_path(Path(key).name)
            if not local_path.exists():
                self.client.download_file(self.bucket, key, str(local_path))
            return local_path
        return Path(stored_path)

    def absolute_to_url(self, abs_path: str) -> str:
        if abs_path.startswith("s3://"):
            _, _, rest = abs_path.partition("s3://")
            _, _, key = rest.partition("/")
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=3600,
            )
        return LocalStorage().absolute_to_url(abs_path)

    def delete_file(self, path: str) -> None:
        if path.startswith("s3://"):
            _, _, rest = path.partition("s3://")
            _, _, key = rest.partition("/")
            self.client.delete_object(Bucket=self.bucket, Key=key)
        else:
            LocalStorage().delete_file(path)


def get_storage() -> LocalStorage | S3Storage:
    """Factory — returns the configured storage backend."""
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage()
