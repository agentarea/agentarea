"""
Infisical Secret Manager Factory

This module provides a factory function to create properly configured 
Infisical secret manager instances based on environment configuration.
"""

import logging
import os
from typing import Optional

from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from agentarea.common.infrastructure.local_secret_manager import LocalSecretManager

logger = logging.getLogger(__name__)


def create_infisical_secret_manager() -> BaseSecretManager:
    """
    Create an Infisical secret manager instance based on configuration.
    
    Returns:
        BaseSecretManager: Configured secret manager instance
    """
    try:
        # Check if Infisical SDK is available
        from infisical_sdk.client import InfisicalSDKClient
        from agentarea.modules.secrets.infisical_secret_manager import InfisicalSecretManager
        
        # Get Infisical configuration from environment
        infisical_url = os.getenv('INFISICAL_URL', 'https://app.infisical.com')
        client_id = os.getenv('INFISICAL_CLIENT_ID')
        client_secret = os.getenv('INFISICAL_CLIENT_SECRET')
        project_id = os.getenv('INFISICAL_PROJECT_ID', 'default')
        environment = os.getenv('INFISICAL_ENVIRONMENT', 'dev')
        
        if not client_id or not client_secret:
            logger.warning("Infisical credentials not configured. Using local file manager.")
            return LocalSecretManager()
        
        # Initialize Infisical client
        client = InfisicalSDKClient(
            client_id=client_id,
            client_secret=client_secret,
            site_url=infisical_url
        )
        
        logger.info(f"Initialized Infisical secret manager for project {project_id} in {environment}")
        return InfisicalSecretManager(client)
        
    except ImportError:
        logger.warning("Infisical SDK not installed. Using local file manager.")
        return LocalSecretManager()
    except Exception as e:
        logger.error(f"Failed to initialize Infisical secret manager: {e}. Using local file manager.")
        return LocalSecretManager()


def get_real_secret_manager() -> BaseSecretManager:
    """
    Get a real secret manager implementation (non-test).
    
    Returns:
        BaseSecretManager: Real secret manager instance
    """
    return create_infisical_secret_manager() 