from typing import List, Optional
from ..schemas import (
    SourceSpecification, 
    SourceCategory, 
    SourceType, 
    ConfigField, 
    ConfigFieldType
)

class SourceSpecificationService:
    """Service for managing source specifications."""
    
    def __init__(self):
        # Initialize with predefined source specifications
        self.specifications = self._initialize_specifications()
    
    def get_specifications(self, category: Optional[SourceCategory] = None) -> List[SourceSpecification]:
        """Get all source specifications, optionally filtered by category."""
        if category:
            return [spec for spec in self.specifications if spec.category == category]
        return self.specifications
    
    def get_specification_by_id(self, spec_id: str) -> Optional[SourceSpecification]:
        """Get a source specification by ID."""
        for spec in self.specifications:
            if spec.id == spec_id:
                return spec
        return None
    
    def _initialize_specifications(self) -> List[SourceSpecification]:
        """Initialize predefined source specifications."""
        return [
            # Database sources
            SourceSpecification(
                id="postgres",
                name="PostgreSQL",
                description="Connect to your PostgreSQL database for data processing",
                icon="database",
                category=SourceCategory.DATABASE,
                type=SourceType.DATABASE,
                config_fields=[
                    ConfigField(
                        name="host",
                        label="Host",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Database host address",
                        placeholder="localhost or database.example.com"
                    ),
                    ConfigField(
                        name="port",
                        label="Port",
                        type=ConfigFieldType.NUMBER,
                        required=True,
                        default=5432,
                        description="Database port"
                    ),
                    ConfigField(
                        name="database",
                        label="Database Name",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Name of the database to connect to"
                    ),
                    ConfigField(
                        name="username",
                        label="Username",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Database username"
                    ),
                    ConfigField(
                        name="password",
                        label="Password",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="Database password"
                    ),
                    ConfigField(
                        name="ssl",
                        label="Use SSL",
                        type=ConfigFieldType.BOOLEAN,
                        default=False,
                        description="Whether to use SSL for the connection"
                    )
                ],
                capabilities=["query", "schema_discovery", "data_extraction"],
                documentation_url="https://www.postgresql.org/docs/"
            ),
            
            # API sources
            SourceSpecification(
                id="rest_api",
                name="REST API",
                description="Connect to a REST API endpoint",
                icon="globe",
                category=SourceCategory.API,
                type=SourceType.API,
                config_fields=[
                    ConfigField(
                        name="base_url",
                        label="Base URL",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Base URL of the API",
                        placeholder="https://api.example.com"
                    ),
                    ConfigField(
                        name="auth_type",
                        label="Authentication Type",
                        type=ConfigFieldType.SELECT,
                        required=True,
                        options=[
                            {"value": "none", "label": "No Authentication"},
                            {"value": "api_key", "label": "API Key"},
                            {"value": "oauth2", "label": "OAuth 2.0"},
                            {"value": "basic", "label": "Basic Auth"}
                        ],
                        default="none"
                    ),
                    ConfigField(
                        name="api_key",
                        label="API Key",
                        type=ConfigFieldType.PASSWORD,
                        required=False,
                        description="API key for authentication",
                        validation={"depends_on": {"auth_type": "api_key"}}
                    ),
                    ConfigField(
                        name="headers",
                        label="Custom Headers",
                        type=ConfigFieldType.STRING,
                        required=False,
                        description="Custom headers in JSON format"
                    )
                ],
                capabilities=["data_fetching", "webhook_support"],
                auth_type="api_key"
            ),
            
            # File sources
            SourceSpecification(
                id="file_upload",
                name="File Upload",
                description="Upload and process files (CSV, Excel, JSON, etc.)",
                icon="upload",
                category=SourceCategory.QUICK_UPLOAD,
                type=SourceType.FILE,
                config_fields=[
                    ConfigField(
                        name="file",
                        label="File",
                        type=ConfigFieldType.FILE,
                        required=True,
                        description="File to upload"
                    ),
                    ConfigField(
                        name="file_type",
                        label="File Type",
                        type=ConfigFieldType.SELECT,
                        required=True,
                        options=[
                            {"value": "csv", "label": "CSV"},
                            {"value": "excel", "label": "Excel"},
                            {"value": "json", "label": "JSON"},
                            {"value": "text", "label": "Text"}
                        ]
                    ),
                    ConfigField(
                        name="has_header",
                        label="Has Header Row",
                        type=ConfigFieldType.BOOLEAN,
                        default=True,
                        description="Whether the file has a header row"
                    )
                ],
                capabilities=["data_import", "schema_inference"]
            ),
            
            # Email sources
            SourceSpecification(
                id="gmail",
                name="Gmail",
                description="Connect to Gmail for email processing",
                icon="mail",
                category=SourceCategory.EMAIL,
                type=SourceType.EMAIL,
                config_fields=[
                    ConfigField(
                        name="email",
                        label="Email Address",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Gmail address to connect to"
                    ),
                    ConfigField(
                        name="oauth_token",
                        label="OAuth Token",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="OAuth token for Gmail API"
                    ),
                    ConfigField(
                        name="labels",
                        label="Labels to Monitor",
                        type=ConfigFieldType.MULTISELECT,
                        required=False,
                        description="Gmail labels to monitor",
                        options=[
                            {"value": "inbox", "label": "Inbox"},
                            {"value": "sent", "label": "Sent"},
                            {"value": "important", "label": "Important"}
                        ],
                        default=["inbox"]
                    )
                ],
                capabilities=["email_monitoring", "attachment_processing"],
                auth_type="oauth2"
            ),
            
            # Storage sources
            SourceSpecification(
                id="s3",
                name="Amazon S3",
                description="Connect to Amazon S3 for file storage and processing",
                icon="file-text",
                category=SourceCategory.STORAGE,
                type=SourceType.STORAGE,
                config_fields=[
                    ConfigField(
                        name="bucket_name",
                        label="Bucket Name",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="S3 bucket name"
                    ),
                    ConfigField(
                        name="region",
                        label="AWS Region",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="AWS region of the bucket",
                        default="us-east-1"
                    ),
                    ConfigField(
                        name="access_key",
                        label="Access Key ID",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="AWS access key ID"
                    ),
                    ConfigField(
                        name="secret_key",
                        label="Secret Access Key",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="AWS secret access key"
                    ),
                    ConfigField(
                        name="prefix",
                        label="Prefix/Folder",
                        type=ConfigFieldType.STRING,
                        required=False,
                        description="Prefix or folder within the bucket"
                    )
                ],
                capabilities=["file_storage", "file_processing"],
                documentation_url="https://docs.aws.amazon.com/s3/"
            ),
            
            # Communication sources
            SourceSpecification(
                id="slack",
                name="Slack",
                description="Connect to Slack for team communication and automation",
                icon="message-square",
                category=SourceCategory.COMMUNICATION,
                type=SourceType.COMMUNICATION,
                config_fields=[
                    ConfigField(
                        name="workspace",
                        label="Workspace Name",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Slack workspace name"
                    ),
                    ConfigField(
                        name="bot_token",
                        label="Bot Token",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="Slack bot token"
                    ),
                    ConfigField(
                        name="channels",
                        label="Channels to Monitor",
                        type=ConfigFieldType.STRING,
                        required=False,
                        description="Comma-separated list of channels to monitor"
                    )
                ],
                capabilities=["message_monitoring", "notification_sending"],
                auth_type="oauth2"
            ),
            
            # E-commerce sources
            SourceSpecification(
                id="shopify",
                name="Shopify",
                description="Connect your Shopify store for e-commerce operations",
                icon="shopping-bag",
                category=SourceCategory.ECOMMERCE,
                type=SourceType.ECOMMERCE,
                config_fields=[
                    ConfigField(
                        name="store_url",
                        label="Store URL",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Your Shopify store URL",
                        placeholder="your-store.myshopify.com"
                    ),
                    ConfigField(
                        name="api_key",
                        label="API Key",
                        type=ConfigFieldType.STRING,
                        required=True,
                        description="Shopify API key"
                    ),
                    ConfigField(
                        name="api_secret",
                        label="API Secret",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="Shopify API secret"
                    ),
                    ConfigField(
                        name="access_token",
                        label="Access Token",
                        type=ConfigFieldType.PASSWORD,
                        required=True,
                        description="Shopify access token"
                    )
                ],
                capabilities=["order_processing", "product_management", "customer_data"],
                auth_type="api_key"
            )
        ] 