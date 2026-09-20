"""Will this Tiled deliver a webhook to that URL? Run it ON THE TILED HOST.

    python can_tiled_reach.py https://reporter.aps.anl.gov:9000/hook

`getfqdn` resolves from wherever it runs, so the only answer that counts
is the one this gives on the machine Tiled runs on.
"""

import socket
import sys

import tiled.catalog  # noqa: F401  import first, or tiled.server.webhooks cycles
from tiled.server.webhooks import check_url_ssrf_safety
from urllib.parse import urlparse

url = sys.argv[1]
host = urlparse(url).hostname or ""

print(f"url:      {url}")
print(f"hostname: {host}")
if not url.startswith("https://"):
    print("\nREFUSED before anything else: the URL must be https.")

try:
    addrs = sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
except OSError as problem:
    print(f"\nCannot resolve {host!r} from here: {problem}")
    raise SystemExit(2) from problem

print("\nresolves to, and what the allow-list would have to say:")
for ip in addrs:
    print(f"   {ip:<40} -> {socket.getfqdn(ip)!r}")

try:
    check_url_ssrf_safety(url, None, None)
    print("\nALLOWED with no configuration. Webhooks will deliver here.")
    raise SystemExit(0)
except ValueError as blocked:
    print(f"\nBLOCKED by default: {blocked}")

names = [socket.getfqdn(ip) for ip in addrs]
usable = [n for n in names if not n.endswith((".in-addr.arpa", ".ip6.arpa")) and n not in addrs]
if not usable:
    print(
        "\nAnd it cannot be allow-listed: there is no reverse-DNS name for these\n"
        "addresses, and Tiled refuses an IP literal in allow_delivery_hosts.\n"
        "Options: get a PTR record for this host, or use an egress proxy,\n"
        "or poll the catalog instead of receiving webhooks."
    )
    raise SystemExit(1)

try:
    check_url_ssrf_safety(url, None, usable)
    print(f"\nALLOWED once configured with:\n   allow_delivery_hosts: {usable}")
except ValueError as still:
    print(f"\nStill blocked even with {usable}: {still}")
    raise SystemExit(1) from still
