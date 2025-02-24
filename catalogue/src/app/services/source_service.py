from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import SourceModel
from ..schemas import SourceCreate, SourceUpdate, SourceResponse, SourceStatus
import uuid

class SourceService:
    def __init__(self, db: Session):
        self.db = db

    async def create_source(self, source: SourceCreate) -> SourceResponse:
        now = datetime.utcnow().isoformat()
        source_id = str(uuid.uuid4())
        
        db_source = SourceModel(
            source_id=source_id,
            name=source.name,
            type=source.type,
            description=source.description,
            configuration=source.configuration,
            meta_data=source.metadata,
            owner=source.owner,
            created_at=now,
            updated_at=now,
            status=SourceStatus.ACTIVE
        )
        
        self.db.add(db_source)
        self.db.commit()
        self.db.refresh(db_source)
        
        return self._to_response(db_source)

    async def get_source(self, source_id: str) -> Optional[SourceResponse]:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        return self._to_response(db_source) if db_source else None

    async def list_sources(self) -> List[SourceResponse]:
        db_sources = self.db.query(SourceModel).all()
        return [self._to_response(s) for s in db_sources]

    async def update_source(self, source_id: str, source: SourceUpdate) -> Optional[SourceResponse]:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        if not db_source:
            return None

        update_data = source.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow().isoformat()

        for key, value in update_data.items():
            setattr(db_source, key, value)

        self.db.commit()
        self.db.refresh(db_source)
        return self._to_response(db_source)

    async def delete_source(self, source_id: str) -> bool:
        db_source = self.db.query(SourceModel).filter(SourceModel.source_id == source_id).first()
        if not db_source:
            return False

        self.db.delete(db_source)
        self.db.commit()
        return True

    def _to_response(self, db_source: SourceModel) -> SourceResponse:
        return SourceResponse(
            source_id=db_source.source_id,
            name=db_source.name,
            type=db_source.type,
            description=db_source.description,
            configuration=db_source.configuration,
            metadata=db_source.meta_data,
            owner=db_source.owner,
            created_at=db_source.created_at,
            updated_at=db_source.updated_at,
            status=db_source.status
        ) 