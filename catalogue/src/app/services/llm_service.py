import json
from typing import Dict, List, Optional
import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..models.llm import LLMInstance as DBLLMInstance, LLMScope
from ..models.llm import LLMReference as DBLLMReference
from ..schemas.llm import ConnectionStatus, LLMInstance, LLMReference


class LLMService:
    def __init__(self, db: Session):
        self.db = db

    async def get_instances(self) -> List[DBLLMInstance]:
        """Получить список всех LLM инстансов"""
        instances = self.db.query(DBLLMInstance).all()
        return [LLMInstance.from_orm(instance) for instance in instances]

    async def add_instance(self, instance: DBLLMInstance) -> LLMInstance:
        """Добавить новый LLM инстанс"""
        db_instance = DBLLMInstance(
            id=instance.id,
            name=instance.name,
            description=instance.description,
            version=instance.version,
            provider=instance.provider,
        )
        self.db.add(db_instance)
        try:
            self.db.commit()
            self.db.refresh(db_instance)
            return LLMInstance.from_orm(db_instance)
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    async def get_references(
        self, scope: Optional[LLMScope] = None
    ) -> List[LLMReference]:
        """Получить список всех LLM референсов с фильтрацией"""
        # join with
        query = self.db.query(DBLLMReference)
        if scope:
            query = query.filter(DBLLMReference.scope == scope)
        references = query.all()
        for ref in references:
            print(ref.settings)
        return [LLMReference.from_orm(ref) for ref in references]

    async def create_reference(
        self, instance_id: uuid.UUID, name: str, settings: Dict, scope: LLMScope
    ) -> LLMReference:
        """Создать новый LLM референс"""
        # Проверяем существование инстанса
        instance = (
            self.db.query(DBLLMInstance)
            .filter(DBLLMInstance.id == instance_id)
            .one_or_none()
        )
        if not instance:
            raise HTTPException(status_code=404, detail="LLM instance not found")

        db_reference = DBLLMReference(
            llm_instance=instance,
            name=name,
            settings=settings,
            scope=scope,
            status="created",
        )
        self.db.add(db_reference)
        try:
            self.db.commit()
            self.db.refresh(db_reference)
            return LLMReference.from_orm(db_reference)
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    async def get_reference(self, reference_id: str) -> Optional[LLMReference]:
        """Получить LLM референс по ID"""
        reference = (
            self.db.query(DBLLMReference)
            .filter(DBLLMReference.id == reference_id)
            .first()
        )
        if not reference:
            return None
        return LLMReference.from_orm(reference)

    async def delete_reference(self, reference_id: str) -> bool:
        """Удалить LLM референс"""
        reference = (
            self.db.query(DBLLMReference)
            .filter(DBLLMReference.id == reference_id)
            .first()
        )
        if not reference:
            return False
        try:
            self.db.delete(reference)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    async def check_connection(self, reference_id: str) -> ConnectionStatus:
        """Проверить соединение с LLM"""
        reference = await self.get_reference(reference_id)
        if not reference:
            raise HTTPException(status_code=404, detail="LLM reference not found")

        # TODO: Implement actual connection check logic
        return ConnectionStatus(
            status="success",
            message="Connection successful",
            latency=0.1,
            additional_info={},
        )
