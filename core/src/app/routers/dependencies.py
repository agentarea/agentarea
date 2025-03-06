from fastapi import Depends
from sqlalchemy.orm import Session

from ..services.model_service import ModelService
from ..config import get_db


def get_model_service(
    db: Session = Depends(get_db),
) -> ModelService:
    return ModelService(db)
