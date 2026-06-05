from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import EvalConfig, ProviderTarget


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SENSITIVE_HEADER_PARTS = ("authorization", "api-key", "apikey", "token", "secret")


@dataclass(frozen=True)
class AuditFinding:
    target: str
    check: str
    status: str
    message: str
    evidence: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def audit_config(config: EvalConfig, online_tls: bool = False) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for target in config.targets:
        findings.extend(_audit_target_static(target))
        if online_tls:
            findings.extend(_audit_target_dns(target))
            findings.extend(_audit_target_tls(target))
    return findings


def _audit_target_static(target: ProviderTarget) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    parsed = urlparse(target.base_url)
    host = parsed.hostname or ""
    scheme = parsed.scheme.lower()

    if scheme == "https":
        findings.append(_finding(target, "transport_scheme", "PASS", "base_url uses HTTPS", target.base_url))
        findings.append(
            _finding(
                target,
                "tls_verification",
                "PASS",
                "client uses default certificate and hostname verification",
                "httpx.AsyncClient default verify=True",
            )
        )
    elif scheme == "http" and host in LOCAL_HOSTS:
        findings.append(
            _finding(
                target,
                "transport_scheme",
                "WARN",
                "HTTP is acceptable only for local mock/dev targets",
                target.base_url,
            )
        )
    elif scheme == "http":
        findings.append(
            _finding(
                target,
                "transport_scheme",
                "FAIL",
                "non-local targets must use HTTPS to reduce MITM risk",
                target.base_url,
            )
        )
    else:
        findings.append(
            _finding(target, "transport_scheme", "FAIL", "base_url must use http or https", target.base_url)
        )

    findings.append(
        _finding(
            target,
            "api_key_storage",
            "PASS",
            "API key is referenced by environment variable name, not stored inline",
            target.api_key_env,
        )
    )

    sensitive_header_findings = 0
    for header_name, header_value in target.headers.items():
        lowered = header_name.lower()
        if any(part in lowered for part in SENSITIVE_HEADER_PARTS):
            sensitive_header_findings += 1
            findings.append(
                _finding(
                    target,
                    "static_secret_headers",
                    "FAIL",
                    "sensitive headers should not be hard-coded in config",
                    header_name,
                )
            )
        elif _looks_like_secret(header_value):
            sensitive_header_findings += 1
            findings.append(
                _finding(
                    target,
                    "static_secret_headers",
                    "FAIL",
                    "header value looks like a static secret",
                    header_name,
                )
            )

    if sensitive_header_findings == 0:
        message = "no static custom headers configured" if not target.headers else "no obvious static secrets in headers"
        findings.append(_finding(target, "static_secret_headers", "PASS", message))
    return findings


def _audit_target_tls(target: ProviderTarget) -> list[AuditFinding]:
    parsed = urlparse(target.base_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return []

    host = parsed.hostname
    port = parsed.port or 443
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=5) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                cert = tls_socket.getpeercert()
                cert_der = tls_socket.getpeercert(binary_form=True)
                protocol = tls_socket.version() or "unknown"
    except Exception as exc:  # noqa: BLE001 - audit should report, not crash.
        return [
            _finding(
                target,
                "tls_handshake",
                "FAIL",
                "TLS handshake or hostname verification failed",
                f"{exc.__class__.__name__}: {exc}",
            )
        ]

    not_after = str(cert.get("notAfter", ""))
    expiry_status, expiry_message = _certificate_expiry_status(not_after)
    fingerprint = hashlib.sha256(cert_der or b"").hexdigest()
    subject = _cert_name(cert.get("subject", ()))
    issuer = _cert_name(cert.get("issuer", ()))
    return [
        _finding(target, "tls_handshake", "PASS", "TLS handshake and hostname verification passed", protocol),
        _finding(target, "certificate_expiry", expiry_status, expiry_message, not_after),
        _finding(target, "certificate_fingerprint", "PASS", "leaf certificate SHA-256 fingerprint captured", fingerprint),
        _finding(target, "certificate_subject", "PASS", "leaf certificate subject captured", subject),
        _finding(target, "certificate_issuer", "PASS", "leaf certificate issuer captured", issuer),
    ]


def _audit_target_dns(target: ProviderTarget) -> list[AuditFinding]:
    parsed = urlparse(target.base_url)
    host = parsed.hostname or ""
    if not host:
        return []
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception as exc:  # noqa: BLE001 - audit should report, not crash.
        return [
            _finding(
                target,
                "dns_resolution",
                "FAIL",
                "host could not be resolved",
                f"{exc.__class__.__name__}: {exc}",
            )
        ]

    addresses = sorted({info[4][0] for info in infos if info and info[4]})
    if not addresses:
        return [_finding(target, "dns_resolution", "WARN", "DNS returned no usable addresses", host)]

    findings = [
        _finding(target, "dns_resolution", "PASS", "host resolved to IP address(es)", ", ".join(addresses[:8]))
    ]
    suspicious = [address for address in addresses if _is_private_or_local_ip(address)]
    if suspicious and host not in LOCAL_HOSTS:
        findings.append(
            _finding(
                target,
                "dns_private_address",
                "WARN",
                "non-local gateway host resolved to private/local IP address(es)",
                ", ".join(suspicious[:8]),
            )
        )
    return findings


def _certificate_expiry_status(not_after: str) -> tuple[str, str]:
    if not not_after:
        return "WARN", "certificate expiry date was not available"
    try:
        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return "WARN", "certificate expiry date could not be parsed"

    days_left = (expiry - datetime.now(timezone.utc)).days
    if days_left < 0:
        return "FAIL", "certificate is expired"
    if days_left < 14:
        return "WARN", f"certificate expires soon: {days_left} day(s) left"
    return "PASS", f"certificate validity is acceptable: {days_left} day(s) left"


def _cert_name(value: object) -> str:
    parts: list[str] = []
    if not isinstance(value, tuple):
        return ""
    for group in value:
        if not isinstance(group, tuple):
            continue
        for item in group:
            if isinstance(item, tuple) and len(item) == 2:
                parts.append(f"{item[0]}={item[1]}")
    return ", ".join(parts)


def _is_private_or_local_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
    )


def _finding(
    target: ProviderTarget,
    check: str,
    status: str,
    message: str,
    evidence: str | None = None,
) -> AuditFinding:
    return AuditFinding(target=target.name, check=check, status=status, message=message, evidence=evidence)


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    if any(prefix in lowered for prefix in ("bearer ", "sk-", "api_key=", "token=")):
        return True
    return len(value) >= 32 and any(character.isdigit() for character in value)
