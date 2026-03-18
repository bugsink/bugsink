import ipaddress
import socket
from urllib.parse import urlparse

from bugsink.app_settings import get_settings


def _parse_networks(cidr_list, setting_name):
    networks = []
    for cidr in cidr_list:
        value = cidr.strip()
        if value == "":
            continue
        try:
            networks.append(ipaddress.ip_network(value))
        except ValueError as e:
            raise ValueError(f"Invalid CIDR in {setting_name}: {value}") from e
    return networks


def _parse_hosts_and_networks(entries, setting_name):
    hosts = set()
    networks = []
    for entry in entries:
        value = entry.strip().lower()
        if value == "":
            continue
        if "://" in value:
            raise ValueError(f"Invalid entry in {setting_name}: {value} (use hostname/IP/CIDR, not full URLs)")
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
            continue
        except ValueError:
            if "/" in value:
                raise ValueError(f"Invalid entry in {setting_name}: {value}") from None
        hosts.add(value)
    return hosts, networks


def _resolve_ip_addresses(hostname, port):
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return {info[4][0] for info in infos}


def _match_entries(target_hostname, resolved_ips, hosts, networks):
    return target_hostname in hosts or any(ip in network for ip in resolved_ips for network in networks)


def validate_webhook_url(webhook_url):
    parsed = urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Webhook URL must use http:// or https://.")
    if parsed.hostname is None:
        raise ValueError("Webhook URL must include a hostname.")

    hostname = parsed.hostname.lower()
    settings = get_settings()
    mode = settings.ALERTS_WEBHOOK_OUTBOUND_MODE

    allow_hosts, allow_networks = _parse_hosts_and_networks(
        settings.ALERTS_WEBHOOK_ALLOW_LIST, "ALERTS_WEBHOOK_ALLOW_LIST")
    deny_hosts, deny_networks = _parse_hosts_and_networks(
        settings.ALERTS_WEBHOOK_DENY_LIST, "ALERTS_WEBHOOK_DENY_LIST")
    disallowed_overlay_networks = _parse_networks(
        settings.ALERTS_WEBHOOK_DISALLOWED_IP_CIDRS, "ALERTS_WEBHOOK_DISALLOWED_IP_CIDRS")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    # Resolve on every send to defend against DNS changes after configuration time.
    try:
        resolved_ips = {ipaddress.ip_address(ip) for ip in _resolve_ip_addresses(parsed.hostname, port)}
    except OSError as e:
        raise ValueError(f"Webhook hostname could not be resolved: {parsed.hostname}") from e

    allow_match = _match_entries(hostname, resolved_ips, allow_hosts, allow_networks)
    deny_match = _match_entries(hostname, resolved_ips, deny_hosts, deny_networks)

    if mode == "allowlist_only" and not allow_match:
        raise ValueError(
            f"Webhook target {hostname} is not allowlisted in ALERTS_WEBHOOK_ALLOW_LIST "
            "(mode=allowlist_only)."
        )

    if deny_match:
        raise ValueError(
            f"Webhook target {hostname} matches ALERTS_WEBHOOK_DENY_LIST."
        )

    for ip in resolved_ips:
        if settings.ALERTS_WEBHOOK_DENY_NON_GLOBAL and not ip.is_global:
            raise ValueError(
                f"Webhook target resolves to non-global IP address {ip}. "
                "If this destination is intentional, add it to ALERTS_WEBHOOK_ALLOW_LIST."
            )
        if any(ip in network for network in disallowed_overlay_networks):
            raise ValueError(
                f"Webhook target resolves to disallowed IP address {ip}. "
                "If this destination is intentional, adjust ALERTS_WEBHOOK_DISALLOWED_IP_CIDRS."
            )
