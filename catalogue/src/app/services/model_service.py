import json
from typing import Dict, List, Optional
import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..models.model import ModelInstance as DBModelInstance, ModelScope
from ..models.model import ModelReference as DBModelReference
from ..schemas.model import ConnectionStatus, ModelInstance, ModelReference


class ModelService:
    def __init__(self, db: Session):
        self.db = db

    async def get_instances(self) -> List[DBModelInstance]:
        """Получить список всех Model инстансов"""
        instances = self.db.query(DBModelInstance).all()
        return [ModelInstance.from_orm(instance) for instance in instances]

    async def add_instance(self, instance: DBModelInstance) -> ModelInstance:
        """Добавить новый Model инстанс"""
        db_instance = DBModelInstance(
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
            return ModelInstance.from_orm(db_instance)
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    async def get_references(
        self, scope: Optional[ModelScope] = None
    ) -> List[ModelReference]:
        """Получить список всех Model референсов с фильтрацией"""
        # join with
        query = self.db.query(DBModelReference)
        if scope:
            query = query.filter(DBModelReference.scope == scope)
        references = query.all()
        for ref in references:
            print(ref.settings)
        return [ModelReference.from_orm(ref) for ref in references]

    async def create_reference(
        self, instance_id: uuid.UUID, name: str, settings: Dict, scope: ModelScope
    ) -> ModelReference:
        """Создать новый Model референс"""
        # Проверяем существование инстанса
        instance = (
            self.db.query(DBModelInstance)
            .filter(DBModelInstance.id == instance_id)
            .one_or_none()
        )
        if not instance:
            raise HTTPException(status_code=404, detail="Model instance not found")

        db_reference = DBModelReference(
            model_instance=instance,
            name=name,
            settings=settings,
            scope=scope,
            status="created",
        )
        self.db.add(db_reference)
        try:
            self.db.commit()
            self.db.refresh(db_reference)
            return ModelReference.from_orm(db_reference)
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    async def get_reference(self, reference_id: str) -> Optional[ModelReference]:
        """Получить Model референс по ID"""
        reference = (
            self.db.query(DBModelReference)
            .filter(DBModelReference.id == reference_id)
            .first()
        )
        if not reference:
            return None
        return ModelReference.from_orm(reference)

    async def delete_reference(self, reference_id: str) -> bool:
        """Удалить Model референс"""
        reference = (
            self.db.query(DBModelReference)
            .filter(DBModelReference.id == reference_id)
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
        """Проверить соединение с Model"""
        reference = await self.get_reference(reference_id)
        if not reference:
            raise HTTPException(status_code=404, detail="Model reference not found")

        # TODO: Implement actual connection check logic
        return ConnectionStatus(
            status="success",
            message="Connection successful",
            latency=0.1,
            additional_info={},
        )
