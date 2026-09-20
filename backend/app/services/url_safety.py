"""Guards against SSRF (server-side request forgery) when this backend
fetches a URL on the user's behalf (see ingestion.py's _extract_text_from_url).

Without this, a saved "URL" of http://169.254.169.254/latest/meta-data/
(a cloud metadata endpoint) or http://localhost:5432 would be fetched by
*this server*, from *inside its own network* -- letting a user probe or
read internal services the public internet could never reach directly.
Validating the scheme and resolved IP isn't enough on its own either: a
URL that looks external can still redirect to an internal address, so
every redirect hop has to be re-validated too, not just the first URL.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(Exception):
    """Raised when a URL is unsafe for this server to fetch itself --
    wrong scheme, or resolves to a private/internal/loopback address.
    """


def _check_public_url_sync(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Unsupported URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname.")

    try:
        addr_infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host: {parsed.hostname}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"{parsed.hostname} resolves to a non-public address ({ip}).")


async def ensure_public_url(url: str) -> None:
    """Raise UnsafeURLError unless url is http(s) and resolves to a public
    address. DNS resolution is blocking I/O, so it's run off the event
    loop the same way the Gemini calls elsewhere in this codebase are.
    """
    await asyncio.to_thread(_check_public_url_sync, url)
