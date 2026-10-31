
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit


def parse_host_allowlist(value: str) -> frozenset[str]:
    """Return a normalized, exact-match host allowlist."""

    hosts = {item.strip().casefold().rstrip(".") for item in value.split(",") if item.strip()}
    if not hosts:
        raise ValueError("At least one external-service host must be allowlisted")
    return frozenset(hosts)


def validate_external_base_url(url: str, *, allowed_hosts: frozenset[str]) -> str:
    """Validate an HTTPS provider base URL without permitting SSRF-prone hosts."""

    parsed = urlsplit(url.strip())
    if parsed.scheme.casefold() != "https":
        raise ValueError("External service base URLs must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("External service base URLs must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("External service base URLs must not contain query strings or fragments")
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if not hostname:
        raise ValueError("External service base URL must contain a hostname")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("External service base URL uses a blocked local hostname")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("External service base URL resolves to a blocked IP class")
    if hostname not in allowed_hosts:
        raise ValueError("External service hostname is not allowlisted")
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit(("https", parsed.netloc, normalized_path, "", ""))


def validate_external_url(url: str, *, allowed_hosts: frozenset[str]) -> str:
    """Validate a complete HTTPS redirect URL against an exact host allowlist."""

    parsed = urlsplit(url.strip())
    if parsed.scheme.casefold() != "https":
        raise ValueError("External URLs must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("External URLs must not contain credentials")
    if parsed.fragment:
        raise ValueError("External URLs must not contain fragments")
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if not hostname:
        raise ValueError("External URL must contain a hostname")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("External URL uses a blocked local hostname")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("External URL resolves to a blocked IP class")
    if hostname not in allowed_hosts:
        raise ValueError("External URL hostname is not allowlisted")
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))


def validate_public_https_url(url: str) -> str:
    """Validate an untrusted public HTTPS source URL without fetching it."""

    parsed = urlsplit(url.strip())
    if parsed.scheme.casefold() != "https":
        raise ValueError("Source URLs must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Source URLs must not contain credentials")
    if parsed.fragment:
        raise ValueError("Source URLs must not contain fragments")
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if not hostname:
        raise ValueError("Source URL must contain a hostname")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Source URL uses a blocked local hostname")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("Source URL resolves to a blocked IP class")
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))
