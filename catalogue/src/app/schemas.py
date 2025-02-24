from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class SystemRequirements(BaseModel):
    memory_requirements: str = Field(None, description="Minimum memory requirements")
    gpu_requirements: bool = Field(None, description="Whether GPU is required")


class ModuleSpec(BaseModel):
    name: str = Field(..., description="Name of the AI agent")
    version: str = Field(..., description="Version of the agent")
    description: str = Field(
        ..., description="Detailed description of the agent's purpose and capabilities"
    )
    input_format: Dict = Field(..., description="Expected input data format")
    output_format: Dict = Field(..., description="Output data format")
    purpose: str = Field(..., description="Main purpose/use case of the agent")
    author: str = Field(..., description="Author of the agent")
    image: str = Field(..., description="Image of the agent")
    tags: List[str] = Field(
        default_factory=list, description="Tags for categorizing the agent"
    )
    environment: Dict[str, str] = Field(
        default_factory=dict, description="Configuration parameters for the agent"
    )
    license: str = Field(default="MIT", description="License type")
    model_framework: Optional[str] = Field(
        None, description="AI framework used (if applicable)"
    )
    system_requirements: Optional["SystemRequirements"] = Field(
        None, description="System requirements for running the agent"
    )


class ModuleResponse(BaseModel):
    id: str
    metadata: ModuleSpec


class SourceType(str, Enum):
    DATABASE = "database"
    API = "api"
    FILE = "file"
    STREAM = "stream"


class SourceStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class SourceBase(BaseModel):
    name: str = Field(..., description="Name of the source")
    type: SourceType = Field(..., description="Type of the source")
    description: str = Field(..., description="Description of the source")
    configuration: Dict = Field(..., description="Source configuration details")
    metadata: Dict = Field(default_factory=dict, description="Additional metadata")
    owner: str = Field(..., description="Owner of the source")


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    configuration: Optional[Dict] = None
    metadata: Optional[Dict] = None
    status: Optional[SourceStatus] = None


class SourceResponse(SourceBase):
    source_id: str
    created_at: str
    updated_at: str
    status: SourceStatus
