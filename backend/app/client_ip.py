"""Resolve rate-limit identities across the trusted edge proxy chain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address

Network = IPv4Network | IPv6Network


def _parse_ip(value: str | None):
    if not value:
        return None
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def resolve_client_identity(
    peer_host: str | None,
    headers: Mapping[str, str],
    trusted_edge_networks: Sequence[Network],
) -> str:
    """Return Cloudflare's visitor IP only when Railway saw a trusted edge.

    Railway overwrites ``X-Real-IP`` with its remote peer. Cloudflare supplies
    the single-value ``CF-Connecting-IP`` visitor header. Requiring the former
    to belong to an explicitly configured Cloudflare network prevents a direct
    client from forging the latter to evade rate limits.
    """
    edge_ip = _parse_ip(headers.get("x-real-ip"))
    if edge_ip is not None and any(edge_ip in network for network in trusted_edge_networks):
        visitor_ip = _parse_ip(headers.get("cf-connecting-ip"))
        if visitor_ip is not None:
            return visitor_ip.compressed
    return peer_host or "unknown"
