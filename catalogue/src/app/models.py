from sqlalchemy import Boolean, Column, String, JSON, Integer
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ModuleSpecModel(Base):
    __tablename__ = "module_specs"

    id = Column(Integer, primary_key=True)
    module_id = Column(String, unique=True, index=True)
    name = Column(String)
    version = Column(String)
    description = Column(String)
    input_format = Column(JSON)
    output_format = Column(JSON)
    purpose = Column(String)
    image = Column(String)
    author = Column(String)
    tags = Column(JSON)
    environment = Column(JSON)
    license = Column(String)
    model_framework = Column(String, nullable=True)
    memory_requirements = Column(String, nullable=True)
    gpu_requirements = Column(Boolean, nullable=True)


class SourceModel(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    source_id = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # e.g., 'database', 'api', 'file'
    description = Column(String)
    configuration = Column(JSON)  # Store connection details, credentials, etc.
    meta_data = Column(JSON)  # Additional metadata (renamed from metadata)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    status = Column(String, nullable=False)  # 'active', 'inactive', 'error'
    owner = Column(String, nullable=False)
