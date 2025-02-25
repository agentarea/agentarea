from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class SourceType(str, Enum):
    DATABASE = "database"
    API = "api"
    FILE = "file"
    STREAM = "stream"
    EMAIL = "email"
    STORAGE = "storage"
    COMMUNICATION = "communication"
    ECOMMERCE = "ecommerce"


class SourceStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    CONNECTING = "connecting"
    SYNCING = "syncing"


class SourceCategory(str, Enum):
    DATABASE = "Database"
    API = "API"
    FILE = "File"
    COMMUNICATION = "Communication"
    STORAGE = "Storage"
    ECOMMERCE = "E-commerce"
    EMAIL = "Email"
    ANALYTICS = "Analytics"
    PROJECT_MANAGEMENT = "Project Management"
    VERSION_CONTROL = "Version Control"
    QUICK_UPLOAD = "Quick Upload"


class ConfigFieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    PASSWORD = "password"
    SELECT = "select"
    MULTISELECT = "multiselect"
    FILE = "file"


class ConfigField(BaseModel):
    name: str = Field(..., description="Field name")
    label: str = Field(..., description="Human-readable label")
    type: ConfigFieldType = Field(..., description="Field type")
    required: bool = Field(default=False, description="Whether the field is required")
    description: Optional[str] = Field(None, description="Field description")
    default: Optional[Any] = Field(None, description="Default value")
    options: Optional[List[Dict[str, str]]] = Field(
        None, description="Options for select fields"
    )
    placeholder: Optional[str] = Field(None, description="Placeholder text")
    validation: Optional[Dict[str, Any]] = Field(None, description="Validation rules")


class SourceSpecification(BaseModel):
    id: str = Field(..., description="Unique identifier for the source type")
    name: str = Field(..., description="Display name of the source type")
    description: str = Field(..., description="Description of the source type")
    icon: str = Field(..., description="Icon identifier")
    category: SourceCategory = Field(..., description="Category of the source")
    type: SourceType = Field(..., description="Technical type of the source")
    config_fields: List[ConfigField] = Field(
        ..., description="Configuration fields required"
    )
    capabilities: List[str] = Field(
        default_factory=list, description="Capabilities of this source type"
    )
    documentation_url: Optional[str] = Field(None, description="URL to documentation")
    auth_type: Optional[str] = Field(
        None, description="Authentication type (oauth, api_key, etc.)"
    )


class SourceBase(BaseModel):
    name: str = Field(..., description="Name of the source")
    type: SourceType = Field(..., description="Type of the source")
    description: str = Field(..., description="Description of the source")
    configuration: Dict = Field(..., description="Source configuration details")
    metadata: Dict = Field(default_factory=dict, description="Additional metadata")
    owner: str = Field(..., description="Owner of the source")
    source_spec_id: Optional[str] = Field(
        None, description="ID of the source specification"
    )


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


class SourceSpecificationResponse(BaseModel):
    specifications: List[SourceSpecification]


class SourceSpecificationRequest(BaseModel):
    category: Optional[SourceCategory] = None
