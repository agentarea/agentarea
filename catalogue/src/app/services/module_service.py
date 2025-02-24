import json
from typing import List, Optional
from sqlalchemy.orm import Session

from ..schemas.module import ModuleSpec, ModuleResponse
from ..models.modules import ModuleSpecModel
from ..config import get_application_config, get_s3_client


class ModuleService:
    def __init__(self, db: Session):
        self.settings = get_application_config()
        self.s3_client = get_s3_client()
        self.bucket_name = self.settings.s3_bucket_name
        self.db = db

    async def save_module(
        self, module_id: str, module_spec: ModuleSpec
    ) -> ModuleResponse:

        # Save metadata to database
        db_spec = ModuleSpecModel(
            module_id=module_id,
            name=module_spec.name,
            version=module_spec.version,
            description=module_spec.description,
            input_format=module_spec.input_format,
            output_format=module_spec.output_format,
            purpose=module_spec.purpose,
            author=module_spec.author,
            image=module_spec.image,
            tags=module_spec.tags,
            environment=module_spec.environment,
            license=module_spec.license,
            model_framework=module_spec.model_framework,
            memory_requirements=(
                module_spec.system_requirements.memory_requirements
                if module_spec.system_requirements
                else None
            ),
            gpu_requirements=(
                module_spec.system_requirements.gpu_requirements
                if module_spec.system_requirements
                else None
            ),
        )

        self.db.add(db_spec)
        self.db.commit()
        self.db.refresh(db_spec)

        return ModuleResponse(id=module_id, metadata=module_spec)

    async def list_modules(self) -> List[ModuleResponse]:
        db_specs = self.db.query(ModuleSpecModel).all()
        return [
            ModuleResponse(
                id=spec.module_id,
                metadata=ModuleSpec(
                    name=spec.name,
                    version=spec.version,
                    description=spec.description,
                    input_format=spec.input_format,
                    output_format=spec.output_format,
                    purpose=spec.purpose,
                    author=spec.author,
                    image=spec.image,
                    tags=spec.tags,
                    environment=spec.environment,
                    license=spec.license,
                    model_framework=spec.model_framework,
                    system_requirements=(
                        {
                            "memory_requirements": spec.memory_requirements,
                            "gpu_requirements": spec.gpu_requirements,
                        }
                        if spec.memory_requirements or spec.gpu_requirements
                        else None
                    ),
                ),
            )
            for spec in db_specs
        ]

    async def get_module(self, module_id: str) -> Optional[ModuleResponse]:
        db_spec = (
            self.db.query(ModuleSpecModel)
            .filter(ModuleSpecModel.module_id == module_id)
            .first()
        )

        if not db_spec:
            return None

        return ModuleResponse(
            id=db_spec.module_id,
            metadata=ModuleSpec(
                name=db_spec.name,
                version=db_spec.version,
                description=db_spec.description,
                input_format=db_spec.input_format,
                output_format=db_spec.output_format,
                purpose=db_spec.purpose,
                author=db_spec.author,
                tags=db_spec.tags,
                image=db_spec.image,
                environment=db_spec.environment,
                license=db_spec.license,
                model_framework=db_spec.model_framework,
                system_requirements=(
                    {
                        "memory_requirements": db_spec.memory_requirements,
                        "gpu_requirements": db_spec.gpu_requirements,
                    }
                    if db_spec.memory_requirements or db_spec.gpu_requirements
                    else None
                ),
            ),
        )
