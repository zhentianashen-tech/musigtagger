# NCM input format

`musigtagger.ncm` reads NetEase Cloud Music `.ncm` containers locally. It does
not download content, invoke an external decoder, or transcode audio. The
encrypted payload is already MP3 or FLAC; decryption changes only its container.

## Container layout

All integer fields are unsigned 32-bit little-endian values.

| Field | Encoding |
| --- | --- |
| Header | 8-byte ASCII magic `CTENFDAM`, then 2 unused bytes |
| Audio key | Length-prefixed data XOR'd with `0x64`, then AES-128-ECB decrypted; PKCS#7 plaintext begins `neteasecloudmusic` |
| Metadata | Length-prefixed data XOR'd with `0x63`; the result begins `163 key(Don't modify):`, followed by Base64 AES-128-ECB data whose PKCS#7 plaintext begins `music:` and UTF-8 JSON |
| CRC | 4 bytes, retained/skipped as container data |
| Image gap | 5 bytes |
| Cover | Length-prefixed image bytes |
| Audio | Remaining bytes, XOR-decrypted in independent chunks of at most 32,768 bytes |

The AES keys used by this implementation are `hzHRAmso5kInbaxW` for the audio
key and `#14ljk_!\\]&0U<'(` for metadata. Static inspection of the operator-provided
YCVideoConverter 1.0.24 `filedecoder` helper independently confirmed both values
in `NeteaseCrypt::sCoreKey` and `NeteaseCrypt::sModifyKey`. The issue's proposed
`hzHRAmso5kIfBYKU` core key and 8-byte `#3Float)` metadata value are not the keys
used by the validated files. The decrypted audio key initializes the NCM
RC4-variant substitution box. For byte position
`j` within each audio chunk (starting at 1), the XOR mask is:

```text
box[(box[j & 255] + box[(box[j & 255] + j) & 255]) & 255]
```

Metadata `musicName`, `artist` (`[[name, id], ...]`), `album`, and `format` are
normalized by the decoder. The decoder checks the declared format against the
actual FLAC/MP3 signature and rejects malformed lengths, padding, JSON, and
unsupported payloads with `NCMFormatError` or `UnsupportedAudioFormatError`.

## Python contract

```python
from musigtagger.ncm import decode, convert_file

track = decode("input.ncm")
track.audio_bytes       # original MP3/FLAC stream, decrypted
track.format            # "mp3" or "flac"
track.extension         # ".mp3" or ".flac"
track.metadata.title    # str | None
track.metadata.artist   # names joined with "/" | None
track.metadata.album    # str | None
track.metadata.raw      # read-only mapping of source JSON
track.cover             # bytes | None
track.track_descriptor("output.flac")  # existing TrackDescriptor contract

convert_file("input.ncm", "output.flac")
```

`decode` performs no writes. `convert_file` creates one new output, restores NCM
metadata and front-cover art using mutagen, and never modifies or deletes the
NCM source. Existing outputs are not overwritten. Conversion preserves all
embedded audio tags already present in the decrypted stream; NCM metadata takes
precedence for the normalized title, artist, album, and cover fields.

## CLI

```bash
musigtagger-ncm input.ncm                 # input.mp3 or input.flac
musigtagger-ncm input.ncm output.flac
python -m musigtagger.ncm input.ncm output.mp3
```

## Validation status

The committed tests generate synthetic NCM containers from the documented
layout and verify round trips for MP3 and FLAC, tags and cover restoration,
malformed input handling, CLI behavior, and source-file integrity. All 47 files
in the operator's read-only library also decode successfully: every payload is
MP3 and every file contains cover art. SHA-256 checks confirmed that decoding
left every source unchanged. A real-sample conversion to MP3 was additionally
parsed with mutagen to verify its audio, normalized tags, and cover bytes.
