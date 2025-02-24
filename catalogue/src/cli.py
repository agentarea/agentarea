import click
import sys
from alembic.config import Config
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import uvicorn
from sqlalchemy import text
from src.app.main import app
from src.app.config import Database, get_db_settings
import os


def get_engine():
    """Get database engine with retry logic"""
    db = Database(get_db_settings())
    return db.engine


def check_database_connection():
    """Check database connection using SQLAlchemy's built-in retry logic"""
    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        raise


def get_current_revision(engine):
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    except Exception as e:
        print(f"Failed to get current revision: {e}")
        return None


def get_head_revision():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def check_migrations_status():
    """Check if all migrations are up to date"""
    engine = get_engine()
    current = get_current_revision(engine)
    head = get_head_revision()

    if current == head:
        print("Migrations are up to date")
        return True
    print(f"Waiting for migrations... (current: {current}, target: {head})")
    raise Exception("Migrations not up to date")


@click.group()
def cli():
    """Catalogue service CLI"""
    pass


@cli.command()
def migrate():
    """Run database migrations"""
    try:
        check_database_connection()
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        print("Migrations completed successfully")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)


@cli.command()
def serve():
    """Start the main application server"""
    check_migrations_status()
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)), 
        # reload=True,
        log_level="info",  # Ensure we see startup messages
        access_log=True    # Log HTTP requests
    )


if __name__ == "__main__":
    cli()
