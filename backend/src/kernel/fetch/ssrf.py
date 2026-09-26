"""Address rules for every outbound request this system makes.

Applies to personal-site fetches, ATS board endpoints and — the one people
forget — the user-supplied LLM base URL. A "Local" model therefore means an
endpoint at a public URL the user controls, not one on our network
(docs/technical_boundaries.md section 4).

The classifier is pure so it can be unit-tested without a network.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from kernel.errors import BlockedAddressError

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Cloud instance-metadata endpoints. Link-local already covers these, but they
# are named so the reason a request was refused is obvious in the message.
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


def blocked_reason(address: str) -> str | None:
    """Why this IP may not be contacted, or ``None`` when it is fine.

    Pure: no DNS, no sockets.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"{address!r} is not an IP address"

    if ip in _METADATA_ADDRESSES:
        return "cloud instance-metadata address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_private:
        return "private address"
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return "reserved, multicast or unspecified address"
    if isinstance(ip, ipaddress.IPv6Address):
        # IPv4-mapped and 6to4 addresses smuggle private v4 space into v6.
        if ip.ipv4_mapped is not None:
            inner = blocked_reason(str(ip.ipv4_mapped))
            return f"IPv4-mapped {inner}" if inner else None
        if ip.sixtofour is not None:
            inner = blocked_reason(str(ip.sixtofour))
            return f"6to4-embedded {inner}" if inner else None
    if not ip.is_global:
        return "non-global address"
    return None


def resolve_addresses(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to. Separated out so tests can stub it."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedAddressError(f"host {host!r} could not be resolved", host=host) from exc
    return [str(info[4][0]) for info in infos]


def assert_public_url(url: str, *, resolver: object | None = None) -> None:
    """Refuse anything that is not a public http(s) endpoint.

    Every address the host resolves to must pass — a host resolving to one
    public and one private address is refused, which is how DNS rebinding is
    usually attempted.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise BlockedAddressError(
            f"scheme {parts.scheme!r} is not allowed; use http or https", url=url
        )
    if not parts.hostname:
        raise BlockedAddressError("URL has no host", url=url)

    port = parts.port or (443 if parts.scheme == "https" else 80)
    resolve = resolver if callable(resolver) else resolve_addresses
    addresses = resolve(parts.hostname, port)
    if not addresses:
        raise BlockedAddressError(f"host {parts.hostname!r} resolved to nothing", url=url)

    for address in addresses:
        reason = blocked_reason(address)
        if reason is not None:
            raise BlockedAddressError(
                f"{parts.hostname} resolves to a {reason} ({address})",
                url=url,
                address=address,
            )
