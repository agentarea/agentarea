from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import SourceModel
from ..schemas import SourceCreate, SourceUpdate, SourceResponse, SourceStatus, SourceType
import uuid
import boto3
from ..config import get_aws_settings
import os
from fastapi import UploadFile

class SourceService:
    def __init__(self, db: Session):
        self.db = db
        self.aws_settings = get_aws_settings()
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.aws_settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.aws_settings.AWS_SECRET_ACCESS_KEY,
            region_name=self.aws_settings.AWS_REGION,
            endpoint_url=self.aws_settings.AWS_ENDPOINT_URL,
        )

    async def create_source(self, source: SourceCreate) -> SourceResponse:
        now = datetime.utcnow().isoformat()
        source_id = str(uuid.uuid4())
        
        db_source = SourceModel(
            source_id=source_id,
            name=source.name,
            type=source.type,
            description=source.description,
            configuration=source.configuration,
            meta_data=source.metadata,
            owner=source.owner,
            created_at=now,
            updated_at=now,
            status=SourceStatus.ACTIVE
        )
        
        self.db.add(db_source)
        self.db.commit()
        self.db.refresh(db_source)
        
        return self._to_response(db_source)

    async def get_source(self, source_id: str) -> Optional[SourceResponse]:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        return self._to_response(db_source) if db_source else None

    async def list_sources(self) -> List[SourceResponse]:
        db_sources = self.db.query(SourceModel).all()
        return [self._to_response(s) for s in db_sources]

    async def update_source(self, source_id: str, source: SourceUpdate) -> Optional[SourceResponse]:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        if not db_source:
            return None

        update_data = source.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow().isoformat()

        for key, value in update_data.items():
            setattr(db_source, key, value)

        self.db.commit()
        self.db.refresh(db_source)
        return self._to_response(db_source)

    async def delete_source(self, source_id: str) -> bool:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        if not db_source:
            return False

        self.db.delete(db_source)
        self.db.commit()
        return True

    async def upload_file(self, file: UploadFile, file_type: str, description: str = None, owner: str = "system") -> SourceResponse:
        """
        Upload a file to S3 and create a source record in the database.
        
        Args:
            file: The file to upload
            file_type: The type of file (e.g., csv, json, etc.)
            description: Optional description of the file
            owner: The owner of the file
            
        Returns:
            SourceResponse: The created source record
        """
        # Generate a unique ID for the file
        source_id = str(uuid.uuid4())
        
        # Create a unique filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        original_filename = file.filename
        file_extension = os.path.splitext(original_filename)[1] if original_filename else ""
        
        if not file_extension and file_type:
            # If no extension but file_type is provided, use that
            file_extension = f".{file_type.lower()}"
            
        s3_key = f"uploads/{source_id}/{timestamp}{file_extension}"
        
        # Upload the file to S3
        file_content = await file.read()
        self.s3_client.put_object(
            Bucket=self.aws_settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_content,
            ContentType=file.content_type
        )
        
        # Get the S3 URL
        s3_url = f"s3://{self.aws_settings.S3_BUCKET_NAME}/{s3_key}"
        
        # Create a source record in the database
        now = datetime.utcnow().isoformat()
        
        # Create configuration with file details
        configuration = {
            "file_path": s3_key,
            "file_type": file_type,
            "original_filename": original_filename,
            "content_type": file.content_type,
            "s3_url": s3_url
        }
        
        # Create metadata with file details
        metadata = {
            "size_bytes": len(file_content),
            "upload_timestamp": now
        }
        
        # Create the source record
        db_source = SourceModel(
            source_id=source_id,
            name=original_filename or f"Uploaded file {timestamp}",
            type=SourceType.FILE,
            description=description or f"Uploaded {file_type} file",
            configuration=configuration,
            meta_data=metadata,
            owner=owner,
            created_at=now,
            updated_at=now,
            status=SourceStatus.ACTIVE
        )
        
        self.db.add(db_source)
        self.db.commit()
        self.db.refresh(db_source)
        
        return self._to_response(db_source)

    async def generate_presigned_url(self, filename: str, file_type: str, content_type: str = None) -> dict:
        """
        Generate a presigned URL for uploading a file directly to S3.
        
        Args:
            filename: Original filename
            file_type: The type of file (e.g., csv, json, etc.)
            content_type: The content type of the file
            
        Returns:
            dict: Contains presigned URL, source_id, and s3_key
        """
        # Generate a unique ID for the file
        source_id = str(uuid.uuid4())
        
        # Create a unique filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(filename)[1] if filename else ""
        
        if not file_extension and file_type:
            # If no extension but file_type is provided, use that
            file_extension = f".{file_type.lower()}"
            
        s3_key = f"uploads/{source_id}/{timestamp}{file_extension}"
        
        # Generate presigned URL
        presigned_url = self.s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self.aws_settings.S3_BUCKET_NAME,
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )
        
        # Replace internal endpoint with public endpoint if needed
        if self.aws_settings.PUBLIC_S3_ENDPOINT and self.aws_settings.AWS_ENDPOINT_URL:
            # Replace the internal endpoint with the public one
            presigned_url = presigned_url.replace(self.aws_settings.AWS_ENDPOINT_URL, self.aws_settings.PUBLIC_S3_ENDPOINT)
        
        return {
            "presigned_url": presigned_url,
            "source_id": source_id,
            "s3_key": s3_key
        }
        
    async def create_source_after_upload(self, source_id: str, s3_key: str, filename: str, 
                                        file_type: str, content_type: str, file_size: int,
                                        description: str = None, owner: str = "system") -> SourceResponse:
        """
        Create a source record after a file has been uploaded via presigned URL.
        
        Args:
            source_id: The unique ID for the source
            s3_key: The S3 key where the file was uploaded
            filename: Original filename
            file_type: The type of file
            content_type: The content type of the file
            file_size: Size of the file in bytes
            description: Optional description of the file
            owner: The owner of the file
            
        Returns:
            SourceResponse: The created source record
        """
        # Get the S3 URL
        s3_url = f"s3://{self.aws_settings.S3_BUCKET_NAME}/{s3_key}"
        
        # Create a source record in the database
        now = datetime.utcnow().isoformat()
        
        # Create configuration with file details
        configuration = {
            "file_path": s3_key,
            "file_type": file_type,
            "original_filename": filename,
            "content_type": content_type,
            "s3_url": s3_url
        }
        
        # Create metadata with file details
        metadata = {
            "size_bytes": file_size,
            "upload_timestamp": now
        }
        
        # Create the source record
        db_source = SourceModel(
            source_id=source_id,
            name=filename or f"Uploaded file {datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            type=SourceType.FILE,
            description=description or f"Uploaded {file_type} file",
            configuration=configuration,
            meta_data=metadata,
            owner=owner,
            created_at=now,
            updated_at=now,
            status=SourceStatus.ACTIVE
        )
        
        self.db.add(db_source)
        self.db.commit()
        self.db.refresh(db_source)
        
        return self._to_response(db_source)

    def _to_response(self, db_source: SourceModel) -> SourceResponse:
        return SourceResponse(
            source_id=db_source.source_id,
            name=db_source.name,
            type=db_source.type,
            description=db_source.description,
            configuration=db_source.configuration,
            metadata=db_source.meta_data,
            owner=db_source.owner,
            created_at=db_source.created_at,
            updated_at=db_source.updated_at,
            status=db_source.status
        ) 