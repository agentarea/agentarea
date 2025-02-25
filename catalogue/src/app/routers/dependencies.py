from fastapi import Depends
from sqlalchemy.orm import Session

from ..services.llm_service import LLMService
from ..database import init_db
from ..config import get_db


def get_llm_service(
    db: Session = Depends(get_db),
) -> LLMService:
    return LLMService(db)
