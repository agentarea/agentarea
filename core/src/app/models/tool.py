import uuid
from sqlalchemy import Column, String, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..database import Base


class Tool(Base):
    """
    Base tool model for storing tool specifications in the database.
    """

    __tablename__ = "tool"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=False)
    input_schema = Column(JSON, nullable=False)
    output_schema = Column(JSON, nullable=False)
    type = Column(String, nullable=False)

    # Relationship with MCPTool
    mcp_tool = relationship("MCPTool", back_populates="tool", uselist=False)


class MCPTool(Base):
    """
    MCP-specific tool model with additional attributes.
    """

    __tablename__ = "mcp_tools"

    id = Column(UUID(as_uuid=True), ForeignKey("tool.id"), primary_key=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    image = Column(String, nullable=False)

    # Relationship with base Tool
    tool = relationship("Tool", back_populates="mcp_tool")
