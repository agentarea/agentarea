from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import ModuleSpecModel
from ..schemas import ModuleSpec, ModuleResponse

class ModuleService:
    def __init__(self, db: Session):
        self.db = db

    async def save_module(self, module_id: str, metadata: ModuleSpec) -> ModuleResponse:
        now = datetime.utcnow().isoformat()
        
        db_module = ModuleSpecModel(
            module_id=module_id,
            name=metadata.name,
            description=metadata.description,
            version=metadata.version,
            author=metadata.author,
            dependencies=metadata.dependencies,
            created_at=now,
            updated_at=now
        )
        
        self.db.add(db_module)
        self.db.commit()
        self.db.refresh(db_module)
        
        return self._to_response(db_module)

    async def get_module(self, module_id: str) -> Optional[ModuleResponse]:
        db_module = self.db.query(ModuleSpecModel).filter(ModuleSpecModel.module_id == module_id).first()
        return self._to_response(db_module) if db_module else None

    async def list_modules(self) -> List[ModuleResponse]:
        db_modules = self.db.query(ModuleSpecModel).all()
        return [self._to_response(m) for m in db_modules]

    def _to_response(self, db_module: ModuleSpecModel) -> ModuleResponse:
        return ModuleResponse(
            module_id=db_module.module_id,
            metadata=ModuleSpec(
                name=db_module.name,
                description=db_module.description,
                version=db_module.version,
                author=db_module.author,
                dependencies=db_module.dependencies,
                created_at=db_module.created_at,
                updated_at=db_module.updated_at
            )
        )
