"""Per-tenant API credential: generate/verify/hash + JSON (de)serialization.

Only a salted SHA-256 HASH is ever persisted — the plaintext (a 32-byte
urlsafe secret) is returned once at issue time and never stored. Tenant is
identified out-of-band (Host subdomain), so the token carries no tenant id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass

_PREFIX = "tnt_"


@dataclass(frozen=True)
class CredentialEntry:
    key_id: str
    salt: str  # hex
    hash: str  # hex sha256(salt_bytes + plaintext_bytes)
    created_at: str
    revoked_at: str = ""


def _hash(salt_hex: str, plaintext: str) -> str:
    return hashlib.sha256(bytes.fromhex(salt_hex) + plaintext.encode("utf-8")).hexdigest()


def generate_credential(*, now: str) -> tuple[str, CredentialEntry]:
    plaintext = _PREFIX + secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    entry = CredentialEntry(secrets.token_hex(4), salt, _hash(salt, plaintext), now)
    return plaintext, entry


def verify(plaintext: str, entries: list[CredentialEntry]) -> CredentialEntry | None:
    if not plaintext or not plaintext.startswith(_PREFIX):
        return None
    for e in entries:
        if e.revoked_at:
            continue
        if hmac.compare_digest(e.hash, _hash(e.salt, plaintext)):
            return e
    return None


def serialize_creds(entries: list[CredentialEntry]) -> str:
    return json.dumps([asdict(e) for e in entries])


def parse_creds(raw: str) -> list[CredentialEntry]:
    return [CredentialEntry(**d) for d in json.loads(raw or "[]")]
