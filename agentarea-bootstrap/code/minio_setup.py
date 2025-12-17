import os
import json
from typing import Optional

import boto3
from botocore.exceptions import ClientError


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    if val is None and default is not None:
        return default
    return val


def minio_setup():
    # Support both MinIO and AWS-style envs
    endpoint_url = _get_env("AWS_ENDPOINT_URL", _get_env("MINIO_ENDPOINT", None))
    access_key = _get_env("AWS_ACCESS_KEY_ID", _get_env("MINIO_ROOT_USER", _get_env("MINIO_ACCESS_KEY", None)))
    secret_key = _get_env(
        "AWS_SECRET_ACCESS_KEY",
        _get_env("MINIO_ROOT_PASSWORD", _get_env("MINIO_SECRET_KEY", None)),
    )
    region = _get_env("AWS_REGION", "us-east-1")

    bucket = _get_env("S3_BUCKET_NAME", _get_env("DOCUMENTS_BUCKET", "documents"))

    # Build S3 client configured for MinIO or AWS
    session = boto3.session.Session()
    s3 = session.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )

    # Ensure bucket exists
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"Bucket '{bucket}' already exists.")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        print(f"Creating bucket '{bucket}'...")
        try:
            if region == "us-east-1":
                s3.create_bucket(Bucket=bucket)
            else:
                s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            print(f"Bucket '{bucket}' created successfully.")
        except ClientError as ce:
            print(f"Failed to create bucket '{bucket}': {ce}")
            raise

    # Try to set public-read policy (similar to `mc policy set public`)
    public_read = _get_env("S3_PUBLIC_READ", "true").lower() in {"1", "true", "yes"}
    if public_read:
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": [
                        "s3:GetObject",
                    ],
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                },
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": [
                        "s3:ListBucket",
                    ],
                    "Resource": f"arn:aws:s3:::{bucket}",
                },
            ],
        }
        try:
            s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
            print(f"Bucket '{bucket}' policy set to public-read.")
        except ClientError as e:
            # Some environments (AWS accounts) block public policies by default
            print(f"Warning: failed to set public policy for '{bucket}': {e}")
