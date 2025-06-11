import os
import requests
import time
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def create_infisical_database():
    """Create the Infisical database if it doesn't exist"""
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "db")
    POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
    
    max_retries = 10
    retry_interval = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            # Connect to the default postgres database to create the infisical database
            conn = psycopg2.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                database="postgres"  # Connect to default database
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            
            # Check if infisical database exists
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'infisical'")
            exists = cursor.fetchone()
            
            if not exists:
                print("Creating Infisical database...")
                cursor.execute("CREATE DATABASE infisical")
                print("✓ Infisical database created successfully")
            else:
                print("✓ Infisical database already exists")
                
            cursor.close()
            conn.close()
            return  # Success, exit the retry loop
            
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries}: Failed to create Infisical database: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
            else:
                print("Failed to create Infisical database after multiple attempts.")
                raise

def infisical_setup():
    # First, create the Infisical database
    create_infisical_database()
    
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "your-secure-password")
    ORGANIZATION_NAME = os.environ.get("ORGANIZATION_NAME", "your-org-name")
    INFISICAL_URL = os.environ.get("INFISICAL_URL", "http://infisical:8080")

    payload = {
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
        "organization": ORGANIZATION_NAME
    }
    url = f"{INFISICAL_URL}/api/v1/admin/bootstrap"
    
    max_retries = 30
    retry_interval = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload)
            status_code = response.status_code

            if status_code == 200:
                print("Successfully bootstrapped Infisical.")
                with open("/app/data/infisical_config.json", "w") as f:
                    f.write(response.text)
                return
            elif status_code == 400:
                print("Infisical instance was already setup.")
                return
            else:
                print(f"Attempt {attempt + 1}/{max_retries}: Service not ready yet...")
                time.sleep(retry_interval)
        except requests.exceptions.RequestException:
            print(f"Attempt {attempt + 1}/{max_retries}: Service not ready yet...")
            time.sleep(retry_interval)
    
    print("Failed to bootstrap Infisical after multiple attempts.")
    print("Please check if the service is running and accessible.")
    exit(1)
