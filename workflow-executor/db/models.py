from sqlalchemy import Column, Integer, String, JSON, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import json

Base = declarative_base()


class TaskContext(Base):
    __tablename__ = "task_contexts"

    id = Column(Integer, primary_key=True)
    task_id = Column(String, unique=True, nullable=False)
    context = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class DatabaseManager:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def save_context(self, task_id: str, context: dict) -> None:
        """Сохраняет или обновляет контекст задачи"""
        session = self.Session()
        try:
            task_context = session.query(TaskContext).filter_by(task_id=task_id).first()
            if task_context:
                task_context.context = context
                task_context.updated_at = datetime.utcnow()
            else:
                task_context = TaskContext(task_id=task_id, context=context)
                session.add(task_context)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_context(self, task_id: str) -> dict:
        """Получает контекст задачи"""
        session = self.Session()
        try:
            task_context = session.query(TaskContext).filter_by(task_id=task_id).first()
            return task_context.context if task_context else {}
        finally:
            session.close()

    def delete_context(self, task_id: str) -> None:
        """Удаляет контекст задачи"""
        session = self.Session()
        try:
            task_context = session.query(TaskContext).filter_by(task_id=task_id).first()
            if task_context:
                session.delete(task_context)
                session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
