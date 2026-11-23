# WAN UDP DNS reply loop

Observed 2026-11-23, 16:16–16:20 Europe/Dublin (UTC). Router, modem, and
Shelly diagnostics were read-only.

## Cause of the DNS failures

The OPNsense WAN rule `Codex WAN UDP/53 state cap` matches IPv4 UDP requests
from the firewall's WAN address to destination port 53. Its loaded PF rule
contains `reply-to (igc0 192.168.0.1)` and `keep state (max 1024)`. The
state for a test lookup to `1.1.1.1:53` carried that rule's label
`13e15b7e-3144-4d6c-a22c-138ece890800` and
`reply-to: 192.168.0.1@igc0`.

The public DNS reply arrived on `igc0` with a valid UDP checksum. The
Ethernet addresses then reversed as OPNsense forwarded the same IPv4 packet
back to the Connect Box. It returned again with the same IP ID, UDP ports,
and DNS transaction ID. TTL decreased from 57 to 56, 55, and 54 across
successive frames. The test socket timed out. Its PF state counted one
outbound packet and 29 inbound matches at the time of inspection. The
rule counter showed zero state-limit hits in the later snapshot.

| Test | Observed result |
| --- | --- |
| Router to `1.1.1.1` and `8.8.8.8` via WAN, UDP/53 | Queries timed out despite replies reaching `igc0` |
| Router to those same resolvers via WAN, TCP/53 | Queries succeeded |
| Router to `1.0.0.1` via WARP, UDP/53 | Queries succeeded |
| Unbound `127.0.0.1:5353` and LAN DNS on both address families | `example.com` returned `SERVFAIL` during testing |
| Mac HTTPS | `example.com` and `www.iana.org` failed to resolve, `www.google.com` returned 200, and fixed-address IPv4 and IPv6 tests worked over WARP |

Unbound forwards general queries to `1.1.1.1` and `1.0.0.1`. During the
incident its infrastructure cache recorded timeouts and an RTO of 120000 ms
for both forwarders. Its log reported that no configured forward server was
usable for the failing queries. Direct UDP probes to the WARP-routed
`1.0.0.1` succeeded while that cached state was present. At 16:20:21, LAN
DNS still returned `SERVFAIL` for `example.com` and `www.iana.org`.

## WAN events

The IPv4 monitor logged a transition to down at 15:10:37 and reported
`Offline` at 16:16:26. The WAN Ethernet link also renegotiated three times
between 16:06 and 16:10. The IPv4 monitor returned to normal at 16:17:09.
At 16:20:21, all four gateway monitors were Online. WAN and LAN Ethernet
were observed at 1 Gbit/s full duplex, and a read-only Shelly query showed
the modem's outlet on. The modem's management page responded to HTTP.
The cause of the earlier WAN and Ethernet events remains unverified.

Related [firewall policy](../operations/opnsense-current-non-default-config.md#firewall-policy)
and [DNS services](../operations/opnsense-current-non-default-config.md#dns-services).
