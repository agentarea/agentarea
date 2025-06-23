import os
import subprocess


def minio_setup():
    MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "minioadmin")
    MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")

    # Configure MinIO client
    subprocess.run(
        [
            "mc",
            "alias",
            "set",
            "myminio",
            MINIO_ENDPOINT,
            MINIO_ROOT_USER,
            MINIO_ROOT_PASSWORD,
        ],
        check=True,
    )

    # Check if bucket exists
    result = subprocess.run(
        ["mc", "ls", "myminio/documents"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print("Creating MinIO documents bucket...")
        subprocess.run(["mc", "mb", "myminio/documents"], check=True)
        subprocess.run(
            ["mc", "policy", "set", "public", "myminio/documents"], check=True
        )
        print("MinIO documents bucket created and set to public.")
    else:
        print("MinIO documents bucket already exists.")
