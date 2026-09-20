"""Verifies a file's actual content against its claimed MIME type.

`UploadFile.content_type` is just the Content-Type header the client sent
-- entirely client-controlled and trivially spoofed (curl -F
"file=@payload;type=image/jpeg" sends whatever type you ask it to,
regardless of the file's real content). Relying on it alone for the
document/image MIME allowlists means that allowlist can be bypassed by
lying about the type, which matters here specifically because a bypassed
file still reaches a Gemini call funded by the shared daily budget.

This only covers the formats with a simple, reliable magic-byte
signature. HEIC/HEIF (ISO-BMFF box format) and every audio format aren't
checked this way -- their signatures are more involved to verify
correctly, and a mismatched file there just wastes one call and fails
cleanly rather than reaching anything sensitive, so the cost/benefit
doesn't justify it here.
"""

_SIMPLE_SIGNATURES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
}


def looks_like_claimed_type(file_bytes: bytes, mime_type: str) -> bool:
    """True if file_bytes' signature matches mime_type, or mime_type isn't
    one this module knows how to verify (in which case it's not our place
    to reject it -- see the module docstring for which types that is).
    """
    if mime_type == "image/webp":
        # RIFF <4-byte size> WEBP -- the size field varies, so it can't be
        # part of a fixed literal signature the way the others are.
        return file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP"

    signatures = _SIMPLE_SIGNATURES.get(mime_type)
    if signatures is None:
        return True
    return any(file_bytes.startswith(signature) for signature in signatures)
