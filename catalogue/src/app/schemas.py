from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SystemRequirements(BaseModel):
    memory_requirements: str = Field(None, description="Minimum memory requirements")
    gpu_requirements: bool = Field(None, description="Whether GPU is required")


class ModuleSpec(BaseModel):
    name: str = Field(..., description="Name of the AI agent")
    version: str = Field(..., description="Version of the agent")
    description: str = Field(
        ..., description="Detailed description of the agent's purpose and capabilities"
    )
    input_format: str = Field(..., description="Expected input data format")
    output_format: str = Field(..., description="Output data format")
    purpose: str = Field(..., description="Main purpose/use case of the agent")
    author: str = Field(..., description="Author of the agent")
    requirements: List[str] = Field(
        default_factory=list, description="Required dependencies"
    )
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
    file_path: str
