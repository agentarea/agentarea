import json
from typing import List, Optional
from botocore.exceptions import ClientError
from fastapi import UploadFile

from .schemas import ModuleSpec, ModuleResponse
from .config import get_settings, get_s3_client


class AgentService:
    def __init__(self):
        self.settings = get_settings()
        self.s3_client = get_s3_client()
        self.bucket_name = self.settings.s3_bucket_name

    async def save_module(
        self, module_id: str, module_file: UploadFile, module_spec: ModuleSpec
    ) -> ModuleResponse:
        # Save module file
        module_content = await module_file.read()
        module_key = f"modules/{module_id}/{module_file.filename}"
        self.s3_client.put_object(
            Bucket=self.bucket_name, Key=module_key, Body=module_content
        )

        # Save metadata
        metadata_key = f"metadata/{module_id}.json"
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=metadata_key,
            Body=module_spec.model_dump_json(),
            ContentType="application/json",
        )

        return ModuleResponse(
            id=module_id,
            metadata=module_spec,
            file_path=f"s3://{self.bucket_name}/{module_key}",
        )

    async def list_modules(self) -> List[ModuleResponse]:
        modules = []
        # List all metadata files
        paginator = self.s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix="metadata/"):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue

                module_id = obj["Key"].split("/")[-1].replace(".json", "")

                # Get metadata
                metadata_obj = self.s3_client.get_object(
                    Bucket=self.bucket_name, Key=obj["Key"]
                )
                metadata = ModuleSpec.model_validate_json(
                    metadata_obj["Body"].read().decode("utf-8")
                )

                # Get module file path
                module_prefix = f"modules/{module_id}/"
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name, Prefix=module_prefix, MaxKeys=1
                )
                if "Contents" in response and response["Contents"]:
                    module_key = response["Contents"][0]["Key"]
                    modules.append(
                        ModuleResponse(
                            id=module_id,
                            metadata=metadata,
                            file_path=f"s3://{self.bucket_name}/{module_key}",
                        )
                    )
        return modules

    async def get_module(self, module_id: str) -> Optional[ModuleResponse]:
        try:
            # Get metadata
            metadata_key = f"metadata/{module_id}.json"
            metadata_obj = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=metadata_key
            )
            metadata = ModuleSpec.model_validate_json(
                metadata_obj["Body"].read().decode("utf-8")
            )

            # Get module file path
            module_prefix = f"modules/{module_id}/"
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=module_prefix, MaxKeys=1
            )
            if "Contents" not in response or not response["Contents"]:
                return None

            module_key = response["Contents"][0]["Key"]
            return ModuleResponse(
                id=module_id,
                metadata=metadata,
                file_path=f"s3://{self.bucket_name}/{module_key}",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
