from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bgb.errors import IntegrityError

MAGIC = b"BGB1"
_NONCE = 12
_AAD = b"BGB1"


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes")
    nonce = os.urandom(_NONCE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _AAD)
    return MAGIC + nonce + ciphertext


def decrypt(blob: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes")
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + _NONCE + 16:
        raise IntegrityError("volume is not an encrypted bgb object")
    nonce = blob[len(MAGIC) : len(MAGIC) + _NONCE]
    ciphertext = blob[len(MAGIC) + _NONCE :]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, _AAD)
    except Exception as exc:
        raise IntegrityError("volume failed authentication") from exc


def parse_key(raw: bytes) -> bytes:
    text = raw.strip()
    if len(text) == 32:
        return text
    try:
        key = bytes.fromhex(text.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("encryption key must be 32 raw bytes or 64 hex characters") from exc
    if len(key) != 32:
        raise ValueError("encryption key must be 32 raw bytes or 64 hex characters")
    return key
