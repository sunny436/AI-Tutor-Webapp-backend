"""What a signed-in device may show about itself: a coarse label and a masked address.

Sessions keep the raw user agent and client IP (auth_sessions) for as long as the session
lives. Neither ever leaves the server: the sessions list returns only

- a label such as "Chrome on Windows", from a small, dependency-free parser that knows the
  common browsers and systems and says "Unknown device" otherwise; and
- the network, not the address: IPv4 keeps its /24 ("203.0.113.x"), IPv6 its /48.

Enough for a person to recognise their own devices; not a tracking identifier.
"""

from __future__ import annotations

import ipaddress
import re

# Order matters: Edge and Opera also say "Chrome", Chrome also says "Safari".
_BROWSERS = (
    ("Edge", re.compile(r"\bEdg(e|A|iOS)?/")),
    ("Opera", re.compile(r"\b(OPR|Opera)/")),
    ("Samsung Internet", re.compile(r"\bSamsungBrowser/")),
    ("Firefox", re.compile(r"\b(Firefox|FxiOS)/")),
    ("Chrome", re.compile(r"\b(Chrome|CriOS)/")),
    ("Safari", re.compile(r"\bVersion/[\d.]+.*\bSafari/")),
)
_SYSTEMS = (
    ("iPad", re.compile(r"\biPad\b")),
    ("iPhone", re.compile(r"\biPhone\b")),
    ("Android", re.compile(r"\bAndroid\b")),
    ("ChromeOS", re.compile(r"\bCrOS\b")),
    ("Windows", re.compile(r"\bWindows\b")),
    ("macOS", re.compile(r"\bMac OS X\b|\bMacintosh\b")),
    ("Linux", re.compile(r"\bLinux\b")),
)


def device_label(user_agent: str | None) -> str:
    agent = user_agent or ""
    browser = next((name for name, pattern in _BROWSERS if pattern.search(agent)), None)
    system = next((name for name, pattern in _SYSTEMS if pattern.search(agent)), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "Unknown device"


def masked_ip(ip: str | None) -> str | None:
    try:
        address = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    if address.version == 4:
        first, second, third, _ = str(address).split(".")
        return f"{first}.{second}.{third}.x"
    network = ipaddress.ip_network(f"{address}/48", strict=False)
    return str(network)
