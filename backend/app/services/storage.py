import os
import shutil
import boto3
from abc import ABC, abstractmethod
from typing import Optional, Generator
from contextlib import contextmanager
from app.core.config import settings
from minio import Minio
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

class StorageService(ABC):
    @abstractmethod
    def upload_file(self, file_obj, destination_path: str, content_type: str = None) -> str:
        """Upload a file-like object to storage. Returns the stored path/key."""
        pass

    @abstractmethod
    def delete_file(self, path: str):
        """Delete a file from storage."""
        pass
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if file exists."""
        pass

    @contextmanager
    @abstractmethod
    def get_local_path(self, path: str) -> Generator[str, None, None]:
        """
        Get a local file path for a stored file.
        For local storage, returns the actual path.
        For remote storage, downloads to a temp file and returns that path.
        Must be used as a context manager to ensure temp file cleanup.
        """
        pass

    @abstractmethod
    def get_presigned_url(self, path: str, expiration: int = 3600) -> str:
        """Get a presigned URL for reading (if applicable) or direct path."""
        pass

class LocalStorage(StorageService):
    def __init__(self, base_dir: str = "/app/uploads"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _full_path(self, path: str) -> str:
        # Prevent traversal
        full_path = os.path.abspath(os.path.join(self.base_dir, path))
        if not full_path.startswith(os.path.abspath(self.base_dir)):
             raise ValueError("Path traversal detected")
        return full_path

    def upload_file(self, file_obj, destination_path: str, content_type: str = None) -> str:
        # If destination_path contains folders, ensure they exist
        full_dest = self._full_path(destination_path)
        os.makedirs(os.path.dirname(full_dest), exist_ok=True)
        
        with open(full_dest, "wb") as buffer:
            shutil.copyfileobj(file_obj, buffer)
        return destination_path

    def delete_file(self, path: str):
        full_path = self._full_path(path)
        if os.path.exists(full_path):
            os.remove(full_path)

    def exists(self, path: str) -> bool:
        return os.path.exists(self._full_path(path))

    @contextmanager
    def get_local_path(self, path: str) -> Generator[str, None, None]:
        yield self._full_path(path)

    def get_presigned_url(self, path: str, expiration: int = 3600) -> str:
        # For local, we assume there's an API endpoint serving this file
        # This might need adjustment depending on how frontend accesses it
        return f"/api/v1/documents/{path}/file" 

class S3BaseStorage(StorageService):
    def __init__(self, endpoint_url: str = None, access_key: str = None, secret_key: str = None, bucket: str = None, region: str = None):
        self.bucket = bucket
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )

    def _ensure_bucket_exists(self):
        """Check if bucket exists, create if not."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                logger.info(f"Bucket {self.bucket} does not exist, creating...")
                try:
                    self.client.create_bucket(Bucket=self.bucket)
                    logger.info(f"Successfully created bucket: {self.bucket}")
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket {self.bucket}: {create_error}")
                    raise
            else:
                logger.error(f"Error checking bucket {self.bucket}: {e}")
                raise

    def upload_file(self, file_obj, destination_path: str, content_type: str = None) -> str:
        self._ensure_bucket_exists()
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        # Reset file pointer if possible
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)

        self.client.upload_fileobj(file_obj, self.bucket, destination_path, ExtraArgs=extra_args)
        return destination_path

    def delete_file(self, path: str):
        self._ensure_bucket_exists()
        self.client.delete_object(Bucket=self.bucket, Key=path)

    def exists(self, path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=path)
            return True
        except:
            return False

    @contextmanager
    def get_local_path(self, path: str) -> Generator[str, None, None]:
        self._ensure_bucket_exists()
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp()
        try:
            with os.fdopen(tmp_fd, 'wb') as tmp_file:
                self.client.download_fileobj(self.bucket, path, tmp_file)
            yield tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def get_presigned_url(self, path: str, expiration: int = 3600) -> str:
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': path},
                ExpiresIn=expiration
            )
            return url
        except Exception as e:
            logger.error(f"Error generating presigned URL: {e}")
            return ""

def get_storage_service() -> StorageService:
    storage_type = settings.STORAGE_TYPE.lower()
    
    if storage_type == "minio":
        endpoint = settings.MINIO_ENDPOINT
        # Ensure http/https
        if not endpoint.startswith("http"):
            protocol = "https" if settings.MINIO_SECURE else "http"
            endpoint = f"{protocol}://{endpoint}"
            
        return S3BaseStorage(
            endpoint_url=endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket=settings.MINIO_BUCKET
        )
    elif storage_type == "s3":
        return S3BaseStorage(
            access_key=settings.AWS_ACCESS_KEY_ID,
            secret_key=settings.AWS_SECRET_ACCESS_KEY,
            region=settings.AWS_REGION,
            bucket=settings.AWS_BUCKET_NAME
        )
    else:
        return LocalStorage()
