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

    async def save_agent(
        self, agent_id: str, agent_file: UploadFile, module_spec: ModuleSpec
    ) -> ModuleResponse:
        # Save agent file
        agent_content = await agent_file.read()
        agent_key = f"agents/{agent_id}/{agent_file.filename}"
        self.s3_client.put_object(
            Bucket=self.bucket_name, Key=agent_key, Body=agent_content
        )

        # Save metadata
        metadata_key = f"metadata/{agent_id}.json"
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=metadata_key,
            Body=module_spec.model_dump_json(),
            ContentType="application/json",
        )

        return ModuleResponse(
            id=agent_id,
            metadata=module_spec,
            file_path=f"s3://{self.bucket_name}/{agent_key}",
        )

    async def list_agents(self) -> List[ModuleResponse]:
        agents = []
        # List all metadata files
        paginator = self.s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix="metadata/"):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue

                agent_id = obj["Key"].split("/")[-1].replace(".json", "")

                # Get metadata
                metadata_obj = self.s3_client.get_object(
                    Bucket=self.bucket_name, Key=obj["Key"]
                )
                metadata = ModuleSpec.model_validate_json(
                    metadata_obj["Body"].read().decode("utf-8")
                )

                # Get agent file path
                agent_prefix = f"agents/{agent_id}/"
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name, Prefix=agent_prefix, MaxKeys=1
                )
                if "Contents" in response and response["Contents"]:
                    agent_key = response["Contents"][0]["Key"]
                    agents.append(
                        ModuleResponse(
                            id=agent_id,
                            metadata=metadata,
                            file_path=f"s3://{self.bucket_name}/{agent_key}",
                        )
                    )
        return agents

    async def get_agent(self, agent_id: str) -> Optional[ModuleResponse]:
        try:
            # Get metadata
            metadata_key = f"metadata/{agent_id}.json"
            metadata_obj = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=metadata_key
            )
            metadata = ModuleSpec.model_validate_json(
                metadata_obj["Body"].read().decode("utf-8")
            )

            # Get agent file path
            agent_prefix = f"agents/{agent_id}/"
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=agent_prefix, MaxKeys=1
            )
            if "Contents" not in response or not response["Contents"]:
                return None

            agent_key = response["Contents"][0]["Key"]
            return ModuleResponse(
                id=agent_id,
                metadata=metadata,
                file_path=f"s3://{self.bucket_name}/{agent_key}",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
