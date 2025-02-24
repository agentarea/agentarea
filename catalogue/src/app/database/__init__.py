from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

Base = declarative_base()


def init_db(url: str):
    def get_db():
        engine = create_engine(
            url,
            echo=True,
        )

        session = sessionmaker(engine, class_=Session)
        with session() as db:
            yield db

    return get_db
