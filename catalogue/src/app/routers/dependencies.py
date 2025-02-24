from fastapi import Depends
from sqlalchemy.orm import Session

from ..services.llm_service import LLMService
from ..database import init_db
from ..config import get_application_config


def get_llm_service(
    db: Session = Depends(init_db(get_application_config().database_url)),
) -> LLMService:
    return LLMService(db)
