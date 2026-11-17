"""Read-only NCM metadata probe for the fixed 47-file set (evaluation ground truth).

Uses the same on-disk field layout as MUSI-12's pushed decoder (commit 4258d90)
but stops after the cover field: it never decrypts the audio payload, so it is
fast and cannot alter any file. This is evaluation-side verification only.
"""

import base64
import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SRC = Path("/test-data/music-source")
MAGIC = b"CTENFDAM"
CORE_KEY = b"hzHRAmso5kInbaxW"
METADATA_KEY = b"#14ljk_!\\]&0U<'("
KEY_XOR = 0x64
METADATA_XOR = 0x63
KEY_PREFIX = b"neteasecloudmusic"
META_PREFIX = b"163 key(Don't modify):"
JSON_PREFIX = b"music:"


def unpad(data):
    if not data or len(data) % 16:
        raise ValueError("bad block length")
    pad = data[-1]
    if not 1 <= pad <= 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad padding")
    return data[:-pad]


def aes_ecb_decrypt(data, key):
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return unpad(dec.update(data) + dec.finalize())


def read_u32(data, off):
    return struct.unpack_from("<I", data, off)[0], off + 4


def take(data, off, n):
    if off + n > len(data):
        raise ValueError("truncated")
    return data[off:off + n], off + n


def key_box(key):
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def sniff(prefix):
    if prefix.startswith(b"fLaC"):
        return "flac"
    if prefix.startswith(b"ID3") or (len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0):
        return "mp3"
    return "unknown"


def probe(path):
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise ValueError("missing CTENFDAM")
    off = len(MAGIC)
    _, off = take(data, off, 2)
    klen, off = read_u32(data, off)
    enc_key, off = take(data, off, klen)
    key_data = aes_ecb_decrypt(bytes(b ^ KEY_XOR for b in enc_key), CORE_KEY)
    if not key_data.startswith(KEY_PREFIX):
        raise ValueError("key prefix mismatch")
    audio_key = key_data[len(KEY_PREFIX):]

    mlen, off = read_u32(data, off)
    enc_meta, off = take(data, off, mlen)
    decoded = bytes(b ^ METADATA_XOR for b in enc_meta)
    if not decoded.startswith(META_PREFIX):
        raise ValueError("metadata prefix mismatch")
    plain = aes_ecb_decrypt(base64.b64decode(decoded[len(META_PREFIX):], validate=True), METADATA_KEY)
    if not plain.startswith(JSON_PREFIX):
        raise ValueError("json prefix mismatch")
    raw = json.loads(plain[len(JSON_PREFIX):].decode("utf-8"))

    _, off = take(data, off, 4)   # CRC
    _, off = take(data, off, 5)   # image gap
    clen, off = read_u32(data, off)
    cover, off = take(data, off, clen)
    payload = data[off:]

    # Decrypt only the first 512 bytes of payload to sniff the container magic.
    n = min(512, len(payload))
    box = key_box(audio_key)
    head = bytearray(payload[:n])
    for idx in range(n):
        j = (idx + 1) & 0xFF
        head[idx] ^= box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF]

    artists = raw.get("artist") or []
    names = [a[0] for a in artists if isinstance(a, (list, tuple)) and a]
    cover_mime = "image/jpeg" if cover.startswith(b"\xff\xd8\xff") else (
        "image/png" if cover.startswith(b"\x89PNG\r\n\x1a\n") else "unknown")
    return {
        "file": path.name,
        "format_declared": raw.get("format"),
        "format_actual": sniff(bytes(head)),
        "title": raw.get("musicName"),
        "artist": "/".join(names) or None,
        "artist_parts": names,
        "album": raw.get("album"),
        "album_id": raw.get("albumId"),
        "duration_ms": raw.get("duration"),
        "bitrate": raw.get("bitrate"),
        "cover_bytes": len(cover),
        "cover_mime": cover_mime,
        "audio_payload_bytes": len(payload),
        "raw_keys": sorted(raw.keys()),
        "raw": raw,
    }


def main():
    out = []
    errors = []
    for p in sorted(SRC.glob("*.ncm")):
        try:
            out.append(probe(p))
        except Exception as exc:  # noqa: BLE001
            errors.append({"file": p.name, "error": f"{type(exc).__name__}: {exc}"})
    summary = {
        "ncm_count": len(list(SRC.glob("*.ncm"))),
        "parsed": len(out),
        "errors": errors,
        "formats_declared": {},
        "formats_actual": {},
        "with_cover": sum(1 for r in out if r["cover_bytes"] > 0),
        "with_title": sum(1 for r in out if r["title"]),
        "with_artist": sum(1 for r in out if r["artist"]),
        "with_album": sum(1 for r in out if r["album"]),
        "total_cover_bytes": sum(r["cover_bytes"] for r in out),
    }
    for r in out:
        summary["formats_declared"][r["format_declared"]] = summary["formats_declared"].get(r["format_declared"], 0) + 1
        summary["formats_actual"][r["format_actual"]] = summary["formats_actual"].get(r["format_actual"], 0) + 1
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "ncm-metadata.json")
    dest.write_text(json.dumps({"summary": summary, "tracks": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("wrote", dest)


if __name__ == "__main__":
    main()
