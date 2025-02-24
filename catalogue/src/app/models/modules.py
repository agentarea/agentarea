from sqlalchemy import Boolean, Column, String, JSON, Integer

from ..database import Base


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
