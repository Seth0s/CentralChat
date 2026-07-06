"""AWS Secrets Manager backend (boto3 when available)."""

from __future__ import annotations

import json
import logging

from app.config import (
    CENTRAL_AWS_SECRETS_PREFIX,
    CENTRAL_AWS_SECRETS_REGION,
)
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.secret_backends.keys import normalize_logical_key, storage_segment

logger = logging.getLogger(__name__)


class AwsSecretsManagerBackend:
    backend_id = "aws"

    def __init__(
        self,
        *,
        region: str | None = None,
        prefix: str | None = None,
        tenant_scoped: bool = True,
    ) -> None:
        self._region = (region or CENTRAL_AWS_SECRETS_REGION).strip() or "us-east-1"
        self._prefix = (prefix or CENTRAL_AWS_SECRETS_PREFIX).strip().strip("/")
        self._tenant_scoped = tenant_scoped
        self._client = None

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3_required_for_aws_secrets_backend") from exc
        self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    def _secret_name(self, logical_key: str) -> str:
        key = storage_segment(logical_key)
        parts = [p for p in (self._prefix, resolve_pg_tenant_id() if self._tenant_scoped else "", key) if p]
        # AWS secret names allow / and alphanumeric plus - _ . @ !
        return "/".join(parts)

    def is_available(self) -> bool:
        try:
            self._client_or_raise().list_secrets(MaxResults=1)
            return True
        except Exception:
            logger.debug("aws secrets manager availability check failed", exc_info=True)
            return False

    def read(self, logical_key: str) -> str:
        key = normalize_logical_key(logical_key)
        if not key:
            return ""
        name = self._secret_name(key)
        try:
            client = self._client_or_raise()
            resp = client.get_secret_value(SecretId=name)
            raw = resp.get("SecretString")
            if not raw:
                return ""
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("value"):
                    return str(parsed["value"]).strip()
            except json.JSONDecodeError:
                pass
            return str(raw).strip()
        except Exception as exc:
            code = ""
            try:
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            except Exception:
                pass
            if code == "ResourceNotFoundException":
                return ""
            logger.debug("aws secrets read failed name=%s", name, exc_info=True)
            return ""

    def write(self, logical_key: str, value: str) -> None:
        key = normalize_logical_key(logical_key)
        stripped = (value or "").strip()
        if not key:
            raise ValueError("invalid_secret_key")
        if not stripped:
            self.delete(key)
            return
        name = self._secret_name(key)
        client = self._client_or_raise()
        payload = json.dumps({"value": stripped})
        try:
            client.put_secret_value(SecretId=name, SecretString=payload)
        except Exception as exc:
            code = ""
            try:
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            except Exception:
                pass
            if code == "ResourceNotFoundException":
                client.create_secret(Name=name, SecretString=payload)
            else:
                raise

    def delete(self, logical_key: str) -> None:
        key = normalize_logical_key(logical_key)
        if not key:
            return
        name = self._secret_name(key)
        try:
            client = self._client_or_raise()
            client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except Exception as exc:
            code = ""
            try:
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            except Exception:
                pass
            if code == "ResourceNotFoundException":
                return
            logger.debug("aws secrets delete failed name=%s", name, exc_info=True)

    def describe(self) -> dict[str, str]:
        return {
            "backend": self.backend_id,
            "region": self._region,
            "prefix": self._prefix,
            "tenant_scoped": "yes" if self._tenant_scoped else "no",
        }
