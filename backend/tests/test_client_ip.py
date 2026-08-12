"""Adversarial trusted-proxy client identity tests."""

from ipaddress import ip_network

from app.client_ip import resolve_client_identity
from app.config import Settings


def test_untrusted_edge_cannot_spoof_visitor_identity() -> None:
    identity = resolve_client_identity(
        "100.64.0.7",
        {
            "x-real-ip": "198.51.100.42",
            "cf-connecting-ip": "203.0.113.99",
            "x-forwarded-for": "203.0.113.99",
        },
        (ip_network("192.0.2.0/24"),),
    )
    assert identity == "100.64.0.7"


def test_trusted_edge_uses_single_cloudflare_visitor_ip() -> None:
    identity = resolve_client_identity(
        "100.64.0.8",
        {
            "x-real-ip": "192.0.2.44",
            "cf-connecting-ip": "2001:db8::5",
            "x-forwarded-for": "spoofed, 2001:db8::5",
        },
        (ip_network("192.0.2.0/24"),),
    )
    assert identity == "2001:db8::5"


def test_invalid_visitor_header_fails_closed_to_direct_peer() -> None:
    identity = resolve_client_identity(
        "100.64.0.9",
        {"x-real-ip": "192.0.2.45", "cf-connecting-ip": "not-an-ip"},
        (ip_network("192.0.2.0/24"),),
    )
    assert identity == "100.64.0.9"


def test_proxy_cidr_configuration_is_validated() -> None:
    settings = Settings(trusted_edge_proxy_cidrs="192.0.2.0/24,2001:db8::/32")
    assert len(settings.trusted_edge_proxy_networks) == 2
