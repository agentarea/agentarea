"""
Integration test for presigned URL functionality.

This tests the complete presigned URL upload flow:
1. Request presigned URL
2. Upload file to S3
3. Create source record
"""

import os
import tempfile
from urllib.parse import urlparse

import pytest
import requests


@pytest.mark.skip(reason="Presigned URL functionality not implemented yet")
@pytest.mark.integration
def test_presigned_url_flow():
    """Test the complete presigned URL upload flow."""
    # Configuration
    api_url = os.environ.get("API_URL", "http://localhost:8000")

    # Create a temporary test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
        temp_file.write("This is a test file for presigned URL upload.")
        test_file_path = temp_file.name

    try:
        # Step 1: Request a presigned URL
        presigned_response = requests.post(
            f"{api_url}/sources/presigned-url/",
            json={
                "filename": "test_file.txt",
                "file_type": "txt",
                "content_type": "text/plain",
            },
            timeout=10,
        )

        assert presigned_response.ok, f"Error getting presigned URL: {presigned_response.text}"

        presigned_data = presigned_response.json()
        presigned_url = presigned_data["presigned_url"]
        source_id = presigned_data["source_id"]
        s3_key = presigned_data["s3_key"]

        # Validate URL structure
        parsed_url = urlparse(presigned_url)
        assert parsed_url.scheme in ["http", "https"], "Invalid URL scheme"
        assert parsed_url.netloc, "Missing hostname in presigned URL"

        # Step 2: Upload the file using the presigned URL
        with open(test_file_path, "rb") as f:
            file_content = f.read()
            upload_response = requests.put(
                presigned_url, data=file_content, headers={"Content-Type": "text/plain"}, timeout=30
            )

        assert upload_response.ok, (
            f"Error uploading file: {upload_response.status_code} - {upload_response.text}"
        )

        # Step 3: Create the source record
        source_response = requests.post(
            f"{api_url}/sources/after-upload/",
            json={
                "source_id": source_id,
                "s3_key": s3_key,
                "filename": "test_file.txt",
                "file_type": "txt",
                "content_type": "text/plain",
                "file_size": len(file_content),
                "description": "Test file uploaded via presigned URL",
                "owner": "test_script",
            },
            timeout=10,
        )

        assert source_response.ok, f"Error creating source record: {source_response.text}"

        source_data = source_response.json()
        assert source_data["source_id"] == source_id
        assert source_data["name"] == "test_file.txt"

    finally:
        # Cleanup: remove temporary file
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)


@pytest.mark.skip(reason="Presigned URL functionality not implemented yet")
@pytest.mark.integration
def test_presigned_url_flow_skip_if_no_server():
    """Test presigned URL flow, but skip if server is not available."""
    api_url = os.environ.get("API_URL", "http://localhost:8000")

    try:
        # Quick health check
        health_response = requests.get(f"{api_url}/health", timeout=5)
        if not health_response.ok:
            pytest.skip(f"Server not available at {api_url}")
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Server not available at {api_url}")
    except requests.exceptions.Timeout:
        pytest.skip(f"Server timeout at {api_url}")

    # If we get here, server is available, run the full test
    test_presigned_url_flow()


if __name__ == "__main__":
    # Allow running as standalone script for debugging
    test_presigned_url_flow_skip_if_no_server()
    print("Test completed successfully!")
