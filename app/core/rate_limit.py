import ipaddress

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings


def _is_ip_in_trusted_proxies(ip_str: str, trusted_proxies: list[str]) -> bool:
    if not trusted_proxies:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for proxy_net in trusted_proxies:
        try:
            if ip in ipaddress.ip_network(proxy_net, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """Spec 9.5: Use request.client.host unless it is inside TRUSTED_PROXIES,
    then take the rightmost non-trusted address from X-Forwarded-For."""
    client_host = request.client.host if request.client else "127.0.0.1"
    trusted = getattr(settings, "TRUSTED_PROXIES", [])
    if not _is_ip_in_trusted_proxies(client_host, trusted):
        return client_host

    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return client_host

    # Parse X-Forwarded-For: list of IPs from left to right (client, proxy1, proxy2, ...)
    ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
    # Walk from right to left to find the rightmost non-trusted address
    for ip_str in reversed(ips):
        if not _is_ip_in_trusted_proxies(ip_str, trusted):
            return ip_str

    return ips[0] if ips else client_host


# Redis storage so limits hold across multiple API processes (Spec 9.5).
# key_func is get_client_ip, extracting the trusted peer or forwarded client.
limiter = Limiter(key_func=get_client_ip, storage_uri=settings.REDIS_URL, key_style="endpoint")
