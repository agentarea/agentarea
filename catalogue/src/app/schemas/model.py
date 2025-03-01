from typing import Optional
import uuid
from pydantic import BaseModel, HttpUrl, Field
from enum import Enum


class ModelScope(str, Enum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class ModelReferenceSpec(BaseModel):
    api_key: Optional[str] = Field(
        None, description="API key for accessing the Model service"
    )
    api_url: Optional[str] = Field(None, description="Model service endpoint URL")
    model_path: Optional[str] = Field(None, description="Path to local model")
    parameters: dict = Field(default={}, description="Additional parameters for Model")

    class Config:
        schema_extra = {
            "example": {
                "api_key": "sk-1234567890abcdef",
                "api_url": "https://api.openai.com/v1",
                "parameters": {"temperature": 0.7, "max_tokens": 1000},
            }
        }
        from_attributes = True


class ModelReference(BaseModel):
    id: uuid.UUID = Field(..., description="Unique reference identifier")
    instance_id: uuid.UUID = Field(..., description="Model instance ID")
    name: str = Field(..., description="Reference name")
    settings: ModelReferenceSpec = Field(..., description="Model connection settings")
    scope: ModelScope = Field(..., description="Visibility scope (PRIVATE/PUBLIC)")
    status: str = Field(..., description="Current reference status")

    class Config:
        schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "instance_id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "GPT-4 Production",
                "settings": {
                    "api_key": "sk-1234567890abcdef",
                    "api_url": "https://api.openai.com/v1",
                    "parameters": {"temperature": 0.7},
                },
                "scope": "PRIVATE",
                "status": "active",
            }
        }
        from_attributes = True


class CreateModelInstance(BaseModel):
    name: str = Field(..., description="Model name")
    description: str = Field(..., description="Model description")
    version: str = Field(..., description="Model version")
    provider: str = Field(..., description="Model provider")

    class Config:
        schema_extra = {
            "example": {
                "name": "GPT-4",
                "description": "OpenAI GPT-4 language model",
                "version": "4.0",
                "provider": "OpenAI",
            }
        }
        from_attributes = True


class ModelInstance(BaseModel):
    id: uuid.UUID = Field(..., description="Unique instance identifier")
    name: str = Field(..., description="Model name")
    description: str = Field(..., description="Model description")
    version: str = Field(..., description="Model version")
    provider: str = Field(..., description="Model provider")

    class Config:
        schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "GPT-4",
                "description": "OpenAI GPT-4 language model",
                "version": "4.0",
                "provider": "OpenAI",
            }
        }
        from_attributes = True


class ConnectionStatus(BaseModel):
    status: str = Field(..., description="Connection status (success/error)")
    message: str = Field(..., description="Status description")
    latency: Optional[float] = Field(None, description="Latency in seconds")
    additional_info: Optional[dict] = Field(None, description="Additional information")

    class Config:
        schema_extra = {
            "example": {
                "status": "success",
                "message": "Successfully connected to GPT-4",
                "latency": 0.123,
                "additional_info": {"model_loaded": True, "available_memory": "4GB"},
            }
        }
        from_attributes = True


class CreateModelReferenceRequest(BaseModel):
    instance_id: uuid.UUID = Field(..., description="Model instance ID")
    settings: ModelReferenceSpec = Field(..., description="Connection settings")
    name: str = Field(..., description="Reference name")
    scope: ModelScope = Field(..., description="Visibility scope")

    class Config:
        schema_extra = {
            "example": {
                "instance_id": "123e4567-e89b-12d3-a456-426614174000",
                "settings": {"api_key": "sk-1234567890abcdef"},
                "name": "My Custom Model",
                "scope": "private",
            }
        }
        from_attributes = True
