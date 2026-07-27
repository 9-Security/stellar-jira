"""Encrypt tenant integration secrets at rest (platform secret derived)."""

from __future__ import annotations

import hashlib
import hmac
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode


def _stream_key(secret_key: str, nonce: bytes, length: int) -> bytes:
    digest = hashlib.sha256(secret_key.encode()).digest()
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(
            digest,
            nonce + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        counter += 1
    return out[:length]


def encrypt_field(plaintext: str, secret_key: str) -> str:
    data = str(plaintext or "").encode()
    if not data:
        return ""
    nonce = os.urandom(16)
    stream = _stream_key(secret_key, nonce, len(data))
    enc = bytes(a ^ b for a, b in zip(data, stream, strict=True))
    return urlsafe_b64encode(nonce + enc).decode()


def decrypt_field(blob: str, secret_key: str) -> str:
    raw = str(blob or "").strip()
    if not raw:
        return ""
    decoded = urlsafe_b64decode(raw.encode())
    if len(decoded) < 17:
        return ""
    nonce, enc = decoded[:16], decoded[16:]
    stream = _stream_key(secret_key, nonce, len(enc))
    plain = bytes(a ^ b for a, b in zip(enc, stream, strict=True))
    return plain.decode()
