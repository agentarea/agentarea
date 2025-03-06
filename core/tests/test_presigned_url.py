import requests
import os
import json
from urllib.parse import urlparse

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")
TEST_FILE_PATH = "test_file.txt"

# Create a test file if it doesn't exist
if not os.path.exists(TEST_FILE_PATH):
    with open(TEST_FILE_PATH, "w") as f:
        f.write("This is a test file for presigned URL upload.")

# Step 1: Request a presigned URL
print("Requesting presigned URL...")
presigned_response = requests.post(
    f"{API_URL}/sources/presigned-url/",
    json={
        "filename": "test_file.txt",
        "file_type": "txt",
        "content_type": "text/plain"
    }
)

if not presigned_response.ok:
    print(f"Error getting presigned URL: {presigned_response.text}")
    exit(1)

presigned_data = presigned_response.json()
presigned_url = presigned_data["presigned_url"]
source_id = presigned_data["source_id"]
s3_key = presigned_data["s3_key"]

print(f"Received presigned URL: {presigned_url}")
print(f"Source ID: {source_id}")
print(f"S3 Key: {s3_key}")

# Parse the URL to check for internal endpoints
parsed_url = urlparse(presigned_url)
hostname = parsed_url.netloc

print(f"Hostname in presigned URL: {hostname}")
if "minio" in hostname or "localhost" not in hostname:
    print("WARNING: The presigned URL contains an internal hostname that might not be accessible from the frontend.")

# Step 2: Upload the file using the presigned URL
print("\nUploading file...")
with open(TEST_FILE_PATH, "rb") as f:
    file_content = f.read()
    upload_response = requests.put(
        presigned_url,
        data=file_content,
        headers={"Content-Type": "text/plain"}
    )

if not upload_response.ok:
    print(f"Error uploading file: {upload_response.status_code} - {upload_response.text}")
    exit(1)

print("File uploaded successfully!")

# Step 3: Create the source record
print("\nCreating source record...")
source_response = requests.post(
    f"{API_URL}/sources/after-upload/",
    json={
        "source_id": source_id,
        "s3_key": s3_key,
        "filename": "test_file.txt",
        "file_type": "txt",
        "content_type": "text/plain",
        "file_size": len(file_content),
        "description": "Test file uploaded via presigned URL",
        "owner": "test_script"
    }
)

if not source_response.ok:
    print(f"Error creating source record: {source_response.text}")
    exit(1)

source_data = source_response.json()
print("Source record created successfully!")
print(f"Source ID: {source_data['source_id']}")
print(f"Source Name: {source_data['name']}")
print(f"Source Type: {source_data['type']}")

print("\nTest completed successfully!") 