#!/usr/bin/env python3

import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import time

def create_temporal_database():
    """Create temporal database if it doesn't exist"""
    print("Creating temporal database...")
    
    # Database connection parameters
    host = os.getenv('POSTGRES_HOST', 'db')
    port = os.getenv('POSTGRES_PORT', '5432')
    user = os.getenv('POSTGRES_USER')
    password = os.getenv('POSTGRES_PASSWORD')
    
    if not user or not password:
        raise ValueError("POSTGRES_USER and POSTGRES_PASSWORD must be set")
    
    # Wait for database to be available
    max_retries = 30
    conn = None
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database='postgres'
            )
            break
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                print(f"Database not ready, waiting... (attempt {attempt + 1}/{max_retries})")
                time.sleep(2)
            else:
                raise e
    
    if conn is None:
        raise RuntimeError("Failed to connect to database")
    
    cursor = None
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if temporal database exists
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'temporal'")
        exists = cursor.fetchone()
        
        if not exists:
            print("Creating temporal database...")
            cursor.execute("CREATE DATABASE temporal")
            print("✓ Temporal database created successfully")
        else:
            print("✓ Temporal database already exists")
            
    except Exception as e:
        print(f"❌ Error creating temporal database: {str(e)}")
        raise
    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

def database_setup():
    """Main database setup function"""
    print("Starting database setup...")
    create_temporal_database()
    print("✓ Database setup completed") 