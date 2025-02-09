#!/bin/bash
# Create S3 bucket
awslocal s3 mb s3://ai-agents-bucket

# Configure CORS
awslocal s3api put-bucket-cors --bucket ai-agents-bucket --cors-configuration '{
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "PUT", "POST"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": []
        }
    ]
}'

# Create required folders structure
awslocal s3api put-object --bucket ai-agents-bucket --key agents/
awslocal s3api put-object --bucket ai-agents-bucket --key metadata/ 