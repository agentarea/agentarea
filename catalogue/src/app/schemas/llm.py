from typing import Optional
import uuid
from pydantic import BaseModel, HttpUrl, Field
from enum import Enum


class LLMScope(str, Enum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class LLMReferenceSpec(BaseModel):
    api_key: Optional[str] = Field(
        None, description="API ключ для доступа к LLM сервису"
    )
    api_url: Optional[str] = Field(None, description="URL эндпоинта LLM сервиса")
    model_path: Optional[str] = Field(None, description="Путь к локальной модели")
    parameters: dict = Field(default={}, description="Дополнительные параметры для LLM")

    class Config:
        schema_extra = {
            "example": {
                "api_key": "sk-1234567890abcdef",
                "api_url": "https://api.openai.com/v1",
                "parameters": {"temperature": 0.7, "max_tokens": 1000},
            }
        }
        from_attributes = True


class LLMReference(BaseModel):
    id: uuid.UUID = Field(..., description="Уникальный идентификатор референса")
    instance_id: uuid.UUID = Field(..., description="ID инстанса LLM")
    name: str = Field(..., description="Имя референса")
    settings: LLMReferenceSpec = Field(..., description="Настройки подключения к LLM")
    scope: LLMScope = Field(..., description="Область видимости (PRIVATE/PUBLIC)")
    status: str = Field(..., description="Текущий статус референса")

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


class CreateLLMInstance(BaseModel):
    name: str = Field(..., description="Название модели")
    description: str = Field(..., description="Описание модели")
    version: str = Field(..., description="Версия модели")
    provider: str = Field(..., description="Провайдер модели")

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


class LLMInstance(BaseModel):
    id: uuid.UUID = Field(..., description="Уникальный идентификатор инстанса")
    name: str = Field(..., description="Название модели")
    description: str = Field(..., description="Описание модели")
    version: str = Field(..., description="Версия модели")
    provider: str = Field(..., description="Провайдер модели")

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
    status: str = Field(..., description="Статус подключения (success/error)")
    message: str = Field(..., description="Описание статуса")
    latency: Optional[float] = Field(None, description="Задержка в секундах")
    additional_info: Optional[dict] = Field(
        None, description="Дополнительная информация"
    )

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


class CreateLLMReferenceRequest(BaseModel):
    instance_id: uuid.UUID = Field(..., description="ID инстанса LLM")
    settings: LLMReferenceSpec = Field(..., description="Настройки подключения")
    name: str = Field(..., description="Имя референса")
    scope: LLMScope = Field(..., description="Область видимости")

    class Config:
        schema_extra = {
            "example": {
                "instance_id": "123e4567-e89b-12d3-a456-426614174000",
                "settings": {"api_key": "sk-1234567890abcdef"},
                "name": "My Custom LLM",
                "scope": "private",
            }
        }
        from_attributes = True
