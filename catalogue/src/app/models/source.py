from sqlalchemy import Boolean, Column, String, JSON, Integer

from ..database import Base


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
