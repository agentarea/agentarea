#!/usr/bin/env python3

import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import time


def wait_for_postgres():
    """Wait for PostgreSQL to be available"""
    print("Waiting for PostgreSQL to be ready...")

    # Database connection parameters
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")

    if not user or not password:
        raise ValueError("POSTGRES_USER and POSTGRES_PASSWORD must be set")

    # Wait for PostgreSQL to be available - connect to default 'postgres' database
    max_retries = 30
    conn = None
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=host, port=port, user=user, password=password, database="postgres"
            )
            print("✓ PostgreSQL is ready")
            conn.close()
            return
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                print(
                    f"PostgreSQL not ready, waiting... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(2)
            else:
                raise e


def create_database_if_not_exists(cursor, db_name, description=""):
    """Create a database if it doesn't exist"""
    try:
        # Check if database exists
        cursor.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (db_name,)
        )
        exists = cursor.fetchone()

        if not exists:
            print(f"  Creating database '{db_name}'{f' ({description})' if description else ''}...")
            cursor.execute(f'CREATE DATABASE "{db_name}"')
            print(f"  ✓ Database '{db_name}' created successfully")
        else:
            print(f"  ✓ Database '{db_name}' already exists")
    except Exception as e:
        print(f"  ❌ Error creating database '{db_name}': {str(e)}")
        raise


def database_setup():
    """Main database setup function - creates all required databases"""
    print("Starting database setup...")
    print("=" * 50)

    # Database connection parameters
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")

    # Database names with defaults
    main_db = os.getenv("POSTGRES_DB", "aiagents")
    temporal_db = os.getenv("TEMPORAL_DB", "temporal")
    infisical_db = os.getenv("INFISICAL_DB", "infisical")
    kratos_db = os.getenv("KRATOS_DB", "kratos")
    hydra_db = os.getenv("HYDRA_DB", "hydra")

    # Wait for PostgreSQL to be ready
    wait_for_postgres()

    print("\nCreating databases...")
    print("-" * 50)

    # Connect to PostgreSQL
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Create all databases
        create_database_if_not_exists(cursor, main_db, "AgentArea main application")
        
        # Only create Infisical database if using Infisical secret manager
        secret_manager_type = os.getenv("SECRET_MANAGER_TYPE", "database").lower()
        if secret_manager_type == "infisical" or os.getenv("INFISICAL_DB"):
            create_database_if_not_exists(cursor, infisical_db, "Secrets management")
        else:
            print(f"  ⊘ Skipping Infisical database (SECRET_MANAGER_TYPE={secret_manager_type})")
        
        create_database_if_not_exists(cursor, temporal_db, "Workflow engine")
        create_database_if_not_exists(cursor, "temporal_visibility", "Temporal visibility")
        create_database_if_not_exists(cursor, kratos_db, "Identity management")
        create_database_if_not_exists(cursor, hydra_db, "OAuth2/OIDC")

        print("-" * 50)
        print("✓ All databases initialized successfully")
        print("\nCreated databases:")
        print(f"  - {main_db} (main application)")
        secret_manager_type = os.getenv("SECRET_MANAGER_TYPE", "database").lower()
        if secret_manager_type == "infisical" or os.getenv("INFISICAL_DB"):
            print(f"  - {infisical_db} (secrets management)")
        print(f"  - {temporal_db} (workflow engine)")
        print(f"  - temporal_visibility (workflow visibility)")
        print(f"  - {kratos_db} (identity management)")
        print(f"  - {hydra_db} (OAuth2/OIDC)")
        print("=" * 50)

    except Exception as e:
        print(f"❌ Error during database setup: {str(e)}")
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
