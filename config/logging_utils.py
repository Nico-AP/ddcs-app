"""Logging utilities for GDPR-compliant logging and email throttling."""

import hashlib
import ipaddress
import logging
import time
from collections import defaultdict


def anonymize_ip_processor(logger, method_name, event_dict):
    """Anonymize IP addresses for GDPR compliance.

    IPv4: Masks last octet (192.168.1.100 -> 192.168.1.0).
    IPv6: Masks last 80 bits (keeps /48 prefix).
    Adds ip_hash (first 8 chars of SHA-256) for correlation.
    """
    if "ip" not in event_dict:
        return event_dict

    ip_str = event_dict["ip"]
    try:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv4Address):
            octets = str(ip).split(".")
            octets[-1] = "0"
            anonymized = ".".join(octets)
        else:
            network = ipaddress.ip_network(f"{ip}/48", strict=False)
            anonymized = str(network.network_address)

        ip_hash = hashlib.sha256(ip_str.encode()).hexdigest()[:8]
        event_dict["ip"] = anonymized
        event_dict["ip_hash"] = ip_hash
    except ValueError:
        event_dict["ip"] = "invalid"

    return event_dict


class ThrottledAdminEmailFilter(logging.Filter):
    """Throttle admin error emails to prevent inbox flooding.

    Groups errors by signature (exception type + module + function).
    Allows max 1 email per signature per throttle_seconds window.
    When an email is sent after suppression, includes a count of
    how many similar errors were suppressed.
    """

    def __init__(self, throttle_seconds=600):
        super().__init__()
        self.throttle_seconds = throttle_seconds
        self._timestamps: dict[str, float] = {}
        self._suppressed_counts: dict[str, int] = defaultdict(int)

    def _get_signature(self, record):
        exc_type = "NoException"
        if record.exc_info and record.exc_info[0]:
            exc_type = record.exc_info[0].__name__
        return f"{exc_type}:{record.module}:{record.funcName}"

    def filter(self, record):
        signature = self._get_signature(record)
        now = time.monotonic()
        last_sent = self._timestamps.get(signature, 0)

        if now - last_sent < self.throttle_seconds:
            self._suppressed_counts[signature] += 1
            return False

        suppressed = self._suppressed_counts.pop(signature, 0)
        if suppressed > 0:
            record.msg = (
                f"[{suppressed} similar error(s) suppressed in the last "
                f"{self.throttle_seconds}s]\n{record.msg}"
            )
            record.args = ()

        self._timestamps[signature] = now
        return True
