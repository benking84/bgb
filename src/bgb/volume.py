from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass

from bgb.errors import IntegrityError

_MAGIC = b"BGBV"
_HEADER = struct.Struct(">I")


@dataclass
class Payload:
    type: str
    header: dict
    blocks: dict[str, bytes]
    entries: list[dict]


def compress(data: bytes) -> bytes:
    return zlib.compress(data, level=6)


def decompress(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error as exc:
        raise IntegrityError("volume payload is not valid zlib data") from exc


def blockset_id(hashes: list[str]) -> str:
    digest = hashlib.sha256()
    for item in hashes:
        digest.update(bytes.fromhex(item))
        digest.update(b"\0")
    if not hashes:
        digest.update(b"bgb-empty-blockset")
    return digest.hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pack(header: dict, body: bytes) -> bytes:
    encoded = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    return _MAGIC + _HEADER.pack(len(encoded)) + encoded + body


def _unpack(payload: bytes) -> tuple[dict, bytes]:
    if not payload.startswith(_MAGIC) or len(payload) < 8:
        raise IntegrityError("volume payload has a bad header")
    (length,) = _HEADER.unpack(payload[4:8])
    end = 8 + length
    if end > len(payload):
        raise IntegrityError("volume payload header is truncated")
    try:
        header = json.loads(payload[8:end])
    except json.JSONDecodeError as exc:
        raise IntegrityError("volume payload header is not json") from exc
    return header, payload[end:]


def encode_blocks(blocks: list[tuple[str, bytes]]) -> bytes:
    entries = []
    body = bytearray()
    for digest, data in blocks:
        if sha256_hex(data) != digest:
            raise IntegrityError("refusing to store a block whose hash does not match")
        entries.append({"h": digest, "n": len(data)})
        body += data
    return _pack({"v": 1, "type": "blocks", "entries": entries}, bytes(body))


def encode_index(volume_name: str, blocks: list[tuple[str, bytes]]) -> bytes:
    header = {
        "v": 1,
        "type": "index",
        "volume": volume_name,
        "entries": [{"h": digest, "n": len(data)} for digest, data in blocks],
    }
    return _pack(header, b"")


def encode_fileset(meta: dict, entries: list[dict]) -> bytes:
    header = {"v": 1, "type": "fileset", "count": len(entries), **meta}
    lines = [json.dumps(entry, separators=(",", ":"), sort_keys=True) for entry in entries]
    body = ("\n".join(lines) + ("\n" if lines else "")).encode()
    return _pack(header, body)


def decode_payload(payload: bytes) -> Payload:
    header, body = _unpack(payload)
    kind = header.get("type")
    if kind == "blocks":
        blocks: dict[str, bytes] = {}
        offset = 0
        for entry in header.get("entries", []):
            size = int(entry["n"])
            chunk = body[offset : offset + size]
            offset += size
            if len(chunk) != size:
                raise IntegrityError("block volume is truncated")
            digest = entry["h"]
            if sha256_hex(chunk) != digest:
                raise IntegrityError(f"block {digest} failed its hash check")
            blocks[digest] = chunk
        if offset != len(body):
            raise IntegrityError("block volume has trailing bytes")
        return Payload("blocks", header, blocks, [])
    if kind == "index":
        return Payload("index", header, {}, [])
    if kind == "fileset":
        entries: list[dict] = []
        if body:
            for line in body.decode().splitlines():
                if line:
                    entries.append(json.loads(line))
        if len(entries) != int(header.get("count", len(entries))):
            raise IntegrityError("fileset volume entry count does not match")
        return Payload("fileset", header, {}, entries)
    raise IntegrityError(f"unknown volume type {kind!r}")


class VolumeWriter:
    def __init__(self, volume_size: int):
        self.volume_size = volume_size
        self._blocks: list[tuple[str, bytes]] = []
        self._bytes = 0

    def add(self, digest: str, data: bytes) -> None:
        self._blocks.append((digest, data))
        self._bytes += len(data)

    def full(self) -> bool:
        return self._bytes >= self.volume_size

    def pending(self) -> bool:
        return bool(self._blocks)

    def take(self) -> list[tuple[str, bytes]]:
        blocks = self._blocks
        self._blocks = []
        self._bytes = 0
        return blocks
