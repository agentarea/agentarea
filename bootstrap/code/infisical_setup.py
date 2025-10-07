import os
import requests
import time


def infisical_setup():
    """Bootstrap Infisical with admin user and organization"""
    print("ℹ️  Note: Infisical database is created by bootstrap_db service")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "your-secure-password")
    ORGANIZATION_NAME = os.environ.get("ORGANIZATION_NAME", "your-org-name")
    INFISICAL_URL = os.environ.get("INFISICAL_URL", "http://infisical:8080")

    payload = {
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
        "organization": ORGANIZATION_NAME,
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
