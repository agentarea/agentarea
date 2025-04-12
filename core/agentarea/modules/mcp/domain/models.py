from datetime import datetime
from typing import List
from uuid import UUID, uuid4

from pydantic import HttpUrl

from agentarea.common.base.model import BaseModel


class MCPServer(BaseModel):
    id: UUID
    name: str
    description: str
    docker_image_url: HttpUrl
    version: str
    tags: List[str]
    status: str
    is_public: bool
    last_updated: datetime

    def __init__(
        self,
        name: str,
        description: str,
        docker_image_url: HttpUrl,
        version: str,
        tags: List[str] = None,
        status: str = "draft",
        is_public: bool = False,
        id: UUID = None,
        last_updated: datetime = None,
    ):
        super().__init__(
            id=id or uuid4(),
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            version=version,
            tags=tags or [],
            status=status,
            is_public=is_public,
            last_updated=last_updated or datetime.utcnow(),
        ) 