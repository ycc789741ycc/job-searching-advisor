"""SSRF rules.

The classifier is pure, so these run with no DNS and no sockets. Address
resolution is stubbed where a URL-level decision is under test.
"""

from __future__ import annotations

import pytest

from kernel.errors import BlockedAddressError
from kernel.fetch import assert_public_url, blocked_reason


@pytest.mark.parametrize(
    ("address", "why"),
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("10.0.0.5", "private"),
        ("192.168.1.10", "private"),
        ("172.16.4.4", "private"),
        ("169.254.169.254", "instance-metadata"),
        ("fd00:ec2::254", "instance-metadata"),
        ("169.254.1.1", "link-local"),
        ("fe80::1", "link-local"),
        ("0.0.0.0", "unspecified"),
        ("224.0.0.1", "multicast"),
        ("::ffff:10.0.0.1", "IPv4-mapped"),
        ("2002:0a00:0001::", "6to4"),
        ("fc00::1", "private"),
    ],
)
def test_non_public_addresses_are_blocked(address: str, why: str) -> None:
    reason = blocked_reason(address)
    assert reason is not None, f"{address} ({why}) must be blocked"


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert blocked_reason(address) is None


def test_garbage_is_not_an_address() -> None:
    assert blocked_reason("not-an-ip") is not None


def test_only_http_schemes_are_allowed() -> None:
    for url in ("file:///etc/passwd", "gopher://host/x", "ftp://host/x"):
        with pytest.raises(BlockedAddressError, match="not allowed"):
            assert_public_url(url, resolver=lambda _h, _p: ["8.8.8.8"])


def test_metadata_endpoint_is_refused_by_url() -> None:
    with pytest.raises(BlockedAddressError, match="instance-metadata"):
        assert_public_url(
            "http://169.254.169.254/latest/meta-data/",
            resolver=lambda _h, _p: ["169.254.169.254"],
        )


def test_a_host_resolving_to_both_public_and_private_is_refused() -> None:
    """The shape of a DNS-rebinding attempt: one good answer, one bad."""
    with pytest.raises(BlockedAddressError, match="private address"):
        assert_public_url(
            "https://rebind.test/callback",
            resolver=lambda _h, _p: ["93.184.216.34", "10.1.2.3"],
        )


def test_a_host_resolving_to_nothing_is_refused() -> None:
    with pytest.raises(BlockedAddressError, match="resolved to nothing"):
        assert_public_url("https://empty.test/", resolver=lambda _h, _p: [])


def test_a_public_llm_base_url_is_allowed() -> None:
    """A user-supplied 'Local' model must be a public endpoint they control."""
    assert_public_url("https://llm.example.com/v1", resolver=lambda _h, _p: ["93.184.216.34"])


def test_localhost_llm_base_url_is_refused() -> None:
    with pytest.raises(BlockedAddressError, match="loopback"):
        assert_public_url("http://localhost:11434/v1", resolver=lambda _h, _p: ["127.0.0.1"])
