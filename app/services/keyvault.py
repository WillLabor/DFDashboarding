"""Azure Key Vault client for storing and retrieving customer API keys.

In production, uses DefaultAzureCredential (managed identity on App Service).
In development, falls back to a local .dev_secrets.json file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_client = None
_SECRETS_FILE = Path(__file__).resolve().parent.parent.parent / ".dev_secrets.json"


def _is_dev() -> bool:
    return os.environ.get("APP_ENV") == "development"


def _get_client():
    global _client
    if _client is None:
        vault_url = os.environ.get("KEY_VAULT_URL")
        if not vault_url:
            raise EnvironmentError(
                "KEY_VAULT_URL environment variable is not set. "
                "Set it in App Settings (Azure) or .env (local)."
            )
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        _client = SecretClient(
            vault_url=vault_url,
            credential=DefaultAzureCredential(),
        )
    return _client


def get_secret(secret_name: str) -> str:
    """Retrieve a secret value from Azure Key Vault (or local file in dev)."""
    if _is_dev():
        if _SECRETS_FILE.exists():
            secrets = json.loads(_SECRETS_FILE.read_text())
            value = secrets.get(secret_name)
            if value:
                return value
        raise ValueError(
            f"Secret '{secret_name}' not found in {_SECRETS_FILE}. "
            "Run the onboarding flow or add it manually."
        )

    client = _get_client()
    return client.get_secret(secret_name).value


def set_secret(secret_name: str, value: str) -> None:
    """Store or update a secret in Azure Key Vault (or local file in dev)."""
    if _is_dev():
        secrets = {}
        if _SECRETS_FILE.exists():
            secrets = json.loads(_SECRETS_FILE.read_text())
        secrets[secret_name] = value
        _SECRETS_FILE.write_text(json.dumps(secrets, indent=2))
        logger.info("Secret '%s' saved to %s (dev mode).", secret_name, _SECRETS_FILE)
        return

    client = _get_client()
    client.set_secret(secret_name, value)
    logger.info("Secret '%s' saved to Key Vault.", secret_name)
