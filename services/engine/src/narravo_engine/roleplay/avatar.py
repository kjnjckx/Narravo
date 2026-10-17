"""Bounded local PNG avatar validation; never fetches a URL or decompresses pixels."""

import base64
import struct
import zlib

PREFIX = "data:image/png;base64,"


def validate(value: str) -> str:
    if not value:
        return value
    if not value.startswith(PREFIX):
        raise ValueError("Use a local PNG avatar")
    raw = base64.b64decode(value[len(PREFIX) :], validate=True)
    if len(raw) > 128 * 1024 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Avatar must be a PNG under 128 KiB")
    offset, count, header = 8, 0, False
    while offset + 12 <= len(raw):
        size = int.from_bytes(raw[offset : offset + 4])
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + size
        if end > len(raw) or count >= 1024 or kind == b"acTL":
            raise ValueError("Invalid or animated avatar")
        data = raw[offset + 8 : end - 4]
        if zlib.crc32(kind + data) != int.from_bytes(raw[end - 4 : end]):
            raise ValueError("Invalid PNG checksum")
        if count == 0:
            if kind != b"IHDR" or size != 13:
                raise ValueError("Missing PNG header")
            width, height = struct.unpack(">II", data[:8])
            if not 0 < width <= 512 or not 0 < height <= 512:
                raise ValueError("Avatar dimensions exceed 512 pixels")
            header = True
        if kind == b"IEND":
            if size or end != len(raw) or not header:
                raise ValueError("Invalid PNG ending")
            return value
        offset = end
        count += 1
    raise ValueError("Incomplete PNG")
