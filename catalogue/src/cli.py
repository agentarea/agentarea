import click
import sys
from alembic.config import Config
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import uvicorn
from sqlalchemy import text
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
@click.option('--host', default="0.0.0.0", help="Host to bind the server to")
@click.option('--port', default=lambda: int(os.getenv("PORT", 8000)), help="Port to bind the server to")
@click.option('--reload/--no-reload', default=False, help="Enable/disable auto-reload on code changes")
@click.option('--log-level', default="info", type=click.Choice(['critical', 'error', 'warning', 'info', 'debug', 'trace']), help="Logging level")
@click.option('--access-log/--no-access-log', default=True, help="Enable/disable access logs")
@click.option('--workers', default=1, help="Number of worker processes")
def serve(host, port, reload, log_level, access_log, workers):
    """Start the main application server"""
    check_migrations_status()
        
    print(f"Starting server on {host}:{port} (reload={reload}, log_level={log_level}, workers={workers})")
    
    # Configure uvicorn
    uvicorn_config = {
        "app": "src.app.main:app",
        "host": host,
        "port": int(port),  # Ensure port is an integer
        "reload": reload,
        "workers": workers,
        "access_log": access_log,
        "log_level": log_level,
    }
    
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    cli()
