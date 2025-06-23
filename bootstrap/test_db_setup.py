#!/usr/bin/env python3
"""
Test script to verify database setup for Infisical
"""

import os
import psycopg2
import sys


def test_database_connection():
    """Test connection to both main and Infisical databases"""
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "db")
    POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "aiagents")

    print("Testing database connections...")

    # Test main database
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DB,
        )
        conn.close()
        print(f"✓ Successfully connected to main database: {POSTGRES_DB}")
    except Exception as e:
        print(f"❌ Failed to connect to main database: {e}")
        return False

    # Test Infisical database
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database="infisical",
        )
        conn.close()
        print("✓ Successfully connected to Infisical database")
    except Exception as e:
        print(f"❌ Failed to connect to Infisical database: {e}")
        return False

    return True


if __name__ == "__main__":
    success = test_database_connection()
    sys.exit(0 if success else 1)
