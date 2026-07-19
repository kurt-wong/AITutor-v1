"""
MinIO Client Layer

Object storage client for file upload/download/listing.
No OCR or file parsing logic — only raw storage operations.

Bucket structure (per DEPLOYMENT.md §10):
- documents: uploaded PDF/DOCX files
- images: extracted page images, wrong-question images
- exports: generated training sets, exam exports
- backup: database dumps
"""

from typing import BinaryIO

from minio import Minio

from app.core.config import settings

def _parse_endpoint(url: str) -> str:
    """Strip protocol prefix from MinIO endpoint URL."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


minio_client = Minio(
    _parse_endpoint(settings.MINIO_URL),
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_URL.startswith("https://"),
)

DEFAULT_BUCKET = settings.MINIO_BUCKET

# Bucket structure per DEPLOYMENT.md §10 + DEPLOYMENT-Phase2 §21.4
BUCKETS = {
    "documents": "Uploaded PDF/DOCX files",
    "images": "Extracted page images, wrong-question images",
    "question-images": "Original and enhanced question images (Phase 2)",
    "exports": "Generated training sets, exam exports",
    "backup": "Database dumps",
}


def ensure_bucket(bucket: str = DEFAULT_BUCKET) -> None:
    """Create bucket if it does not exist."""
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)


def init_buckets() -> None:
    """Initialize all required buckets. Called on application startup."""
    # Ensure default bucket exists
    ensure_bucket(DEFAULT_BUCKET)
    # Ensure named buckets exist
    for bucket_name in BUCKETS:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)


def upload_file(
    object_name: str,
    data: BinaryIO,
    length: int,
    content_type: str = "application/octet-stream",
    bucket: str = DEFAULT_BUCKET,
) -> str:
    """Upload a file to MinIO. Returns the object name."""
    ensure_bucket(bucket)
    minio_client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=data,
        length=length,
        content_type=content_type,
    )
    return object_name


def download_file(
    object_name: str,
    bucket: str = DEFAULT_BUCKET,
) -> bytes:
    """Download a file from MinIO. Returns raw bytes."""
    response = minio_client.get_object(
        bucket_name=bucket,
        object_name=object_name,
    )
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_file(
    object_name: str,
    bucket: str = DEFAULT_BUCKET,
) -> None:
    """Delete a file from MinIO."""
    minio_client.remove_object(bucket, object_name)


def list_files(
    prefix: str = "",
    bucket: str = DEFAULT_BUCKET,
) -> list[str]:
    """List object names in a bucket with optional prefix filter."""
    objects = minio_client.list_objects(
        bucket_name=bucket,
        prefix=prefix,
        recursive=True,
    )
    return [obj.object_name for obj in objects if obj.object_name]


def file_exists(
    object_name: str,
    bucket: str = DEFAULT_BUCKET,
) -> bool:
    """Check if a file exists in MinIO."""
    try:
        minio_client.stat_object(bucket, object_name)
        return True
    except Exception:
        from app.core.logging import get_logger
        get_logger("minio").warning(
            f"stat_object failed for {bucket}/{object_name}", exc_info=True
        )
        return False
