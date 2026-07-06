"""AES-256-GCM envelope encryption for secrets at rest under CENTRAL_ROOT/secrets/."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENVELOPE_VERSION = 1
_NONCE_BYTES = 12


def encryption_enabled() -> bool:
    return _master_key_bytes() is not None


def _master_key_bytes() -> bytes | None:
    raw = (os.getenv("CENTRAL_VAULT_MASTER_KEY") or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            key = bytes.fromhex(raw)
            if len(key) == 32:
                return key
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def is_encrypted_envelope(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("v") == ENVELOPE_VERSION
        and isinstance(data.get("nonce"), str)
        and isinstance(data.get("ciphertext"), str)
    )


def encrypt_value(plaintext: str) -> dict[str, Any]:
    key = _master_key_bytes()
    if not key:
        raise RuntimeError("vault_master_key_missing")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, (plaintext or "").encode("utf-8"), None)
    return {
        "v": ENVELOPE_VERSION,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_value(envelope: dict[str, Any]) -> str:
    if not is_encrypted_envelope(envelope):
        raise ValueError("invalid_encrypted_envelope")
    key = _master_key_bytes()
    if not key:
        raise RuntimeError("vault_master_key_missing")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = base64.b64decode(str(envelope["nonce"]), validate=True)
    ciphertext = base64.b64decode(str(envelope["ciphertext"]), validate=True)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plain.decode("utf-8")


def decode_stored_secret(raw: Any) -> str:
    """Decode plaintext string, legacy {\"value\": ...} doc, or encrypted envelope."""
    if isinstance(raw, str):
        return raw.strip()
    if not isinstance(raw, dict):
        return ""
    if is_encrypted_envelope(raw):
        try:
            return decrypt_value(raw).strip()
        except Exception:
            logger.debug("encrypted_vault: decrypt failed", exc_info=True)
            return ""
    return str(raw.get("value") or raw.get("api_key") or "").strip()


def encode_stored_secret(value: str) -> Any:
    """Encode for persistence — encrypted envelope when master key is set, else plaintext string."""
    stripped = (value or "").strip()
    if not stripped:
        return ""
    if encryption_enabled():
        return encrypt_value(stripped)
    return stripped


def read_json_secrets(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("encrypted_vault: read failed %s", path, exc_info=True)
        return {}


def write_json_secrets(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def read_secret_doc(path: Path) -> str:
    doc = read_json_secrets(path)
    if not doc:
        return ""
    if is_encrypted_envelope(doc):
        return decode_stored_secret(doc)
    return str(doc.get("value") or "").strip()


def write_secret_doc(path: Path, value: str) -> None:
    stripped = (value or "").strip()
    if not stripped:
        if path.is_file():
            path.unlink()
        return
    if encryption_enabled():
        write_json_secrets(path, encrypt_value(stripped))
    else:
        write_json_secrets(path, {"value": stripped})


def load_provider_secrets_map(path: Path) -> dict[str, str]:
    raw = read_json_secrets(path)
    out: dict[str, str] = {}
    changed = False
    for pid, val in raw.items():
        decoded = decode_stored_secret(val)
        if decoded:
            out[str(pid).strip()] = decoded
            if encryption_enabled() and not is_encrypted_envelope(val):
                changed = True
    if changed:
        save_provider_secrets_map(path, out)
    return out


def save_provider_secrets_map(path: Path, secrets: dict[str, str]) -> None:
    encoded: dict[str, Any] = {}
    for pid, val in secrets.items():
        key = str(pid).strip()
        stripped = (val or "").strip()
        if stripped:
            encoded[key] = encode_stored_secret(stripped)
    write_json_secrets(path, encoded)


def migrate_plaintext_at_rest(secrets_dir: Path) -> int:
    """Re-encrypt plaintext secret files when CENTRAL_VAULT_MASTER_KEY is set."""
    if not encryption_enabled():
        return 0
    migrated = 0
    providers_path = secrets_dir / "inference_providers.json"
    if providers_path.is_file():
        before = read_json_secrets(providers_path)
        secrets = load_provider_secrets_map(providers_path)
        after = read_json_secrets(providers_path)
        if before != after and secrets:
            migrated += 1

    values_dir = secrets_dir / "values"
    if values_dir.is_dir():
        for path in values_dir.glob("*.json"):
            doc = read_json_secrets(path)
            if not doc:
                continue
            if is_encrypted_envelope(doc):
                continue
            value = str(doc.get("value") or "").strip()
            if value:
                write_secret_doc(path, value)
                migrated += 1
    return migrated
