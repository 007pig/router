# WAN bandwidth snapshot — 2026-10-01

Observed around 19:46 Europe/Dublin. Read-only SSH diagnostics; no router
settings or client traffic were changed.

Two `pfctl -ss -vv` snapshots approximately 20.04 seconds apart were compared
by state ID and creator ID. Client accounting used only `origif: igc1` inbound
states to public destinations, avoiding duplicate WAN/NAT states. Interface
rates came from `netstat -ibdnW` link counters over the same interval.
DHCP reservations/leases, `arp -an`, and `ndp -an` identified devices and
associated their IPv4 and IPv6 addresses.

| Device | IPv4 identifier | Download, Mbit/s | Upload, Mbit/s |
| --- | --- | ---: | ---: |
| Charles-PC | 192.168.1.29 | 105.85 | 1.65 |
| Xiaoyus-MBP | 192.168.1.115 | 0.39 | 5.16 |
| storj-node-1 | 192.168.1.185 | 0.07 | 3.31 |
| iPhone | 192.168.1.215 | 1.42 | 0.04 |

WAN `igc0` measured 109.03 Mbit/s inbound and 9.82 Mbit/s outbound.
WARP `wg1` measured only 0.148 Mbit/s inbound and 0.168 Mbit/s outbound.
Charles-PC accounted for approximately 97% of measured WAN download traffic.
Its IPv4 traffic contributed 73.07 Mbit/s and its IPv6 address
`fde1:c8ad:df47:4fa0:dc75:537a:6df6:e0f8` contributed 32.78 Mbit/s;
both resolve to MAC `58:6c:25:ff:1e:6e` through ARP/NDP.

Charles-PC had multiple parallel TCP downloads from `151.240.124.125:80`
and a large HTTPS flow from `2a02:26f0:1780:5::216:9017:443`
(IPv6 endpoint, port 443). Router counters alone do not establish the client
application or downloaded content. The Mac had upload traffic to
`149.137.129.99:443`, within the previously documented Backblaze network.
The Storj node's largest observed upload was to `89.187.186.33:7777`, about
3.05 Mbit/s; this does not establish which process owned the connection.

These are approximate short-window rates, not historical usage or proof of
WAN saturation. PF state churn, differences between interface and state
accounting, and sequential counter reads prevent exact reconciliation.
States that disappeared before the second snapshot were not counted.

Related: [network topology and IPv6/WARP routing](ipv6-dslite-opnsense-connectbox.md)
and [non-default configuration](../operations/opnsense-current-non-default-config.md).

## Follow-up: Steam attribution and existing shaper

On the same date, a subsequent 10.06-second sample showed Charles-PC's
largest download endpoints had changed:

| Endpoint | Download, Mbit/s |
| --- | ---: |
| 151.242.228.111:80 | 77.87 |
| 205.234.175.131:80 | 13.65 |
| [2a04:4e42:4e::850]:443 | 3.41 |
| 143.14.15.99:80 | 2.46 |
| [2a02:26f0:1780:f::213:fcda]:443 | 2.30 |

A bounded capture restricted to Charles-PC's HTTP requests to the four
observed IPv4 download endpoints extracted only Host names, including
`edgenext.cdn.steampipe.steamcontent.com`. This confirms Steam content
traffic, but the first capture did not preserve the Host-to-IP association.
A second, payload-only bounded capture returned no Host match.
Reverse DNS for active endpoint `2a01:bc80:4:100::24` returned
`cache14-lhr1.steamcontent.com`; the Akamai endpoint returned a
`deploy.static.akamaitechnologies.com` name.

[RIPE RDAP](https://rdap.db.ripe.net/ip/151.242.228.111) identified
151.242.228.0/24 as Legend Next (UK) Limited, country GB.
RDAP identified the observed 2a04:4e42 address as FASTLY-4E42 and the
2a02:26f0:1780 prefix as AKAMAI-PA. Registration countries and CDN names
do not establish physical server location or identify a downloaded game.

Read-only `ipfw pipe show`, `ipfw queue show`, and `ipfw list` confirmed
the existing 80 Mbit/s pipe 10001 has no active download matching rule.
The five WAN upload class rules remain loaded. No shaper configuration
was changed. Steam-only shaping would need maintained destination matching
for IPv4 and IPv6; shared CDN addresses and changing endpoints mean this
must not be represented as perfect application identification.

## Router-originated WAN speed tests

At the user's request, tested directly on OPNsense with the existing
`speedtest-cli 2.1.3`, bound to WAN `192.168.0.150`. No configuration was
changed. The user canceled router Steam shaping and instead limited Steam
on the client; no new shaper rules or updater jobs were installed.

- Server 65913, Telefonica, Essen, Germany: application download 255.33
  Mbit/s, upload 30.39 Mbit/s, server latency 61.17 ms. Background LAN
  download averaged 99.34 Mbit/s. One-second WAN peaks reached 519.77 Mbit/s
  inbound and 39.14 Mbit/s outbound. Concurrent IPv4 ping reported 21/24
  replies, average RTT 27.51 ms, max 108.93 ms. This ping was interrupted
  when the speed test ended, so an outstanding final probe can contribute
  to the reported loss percentage; do not present it as a precise sustained
  12.5% loss measurement.
- Server 70854, Deutsche Glasfaser, Dusseldorf, Germany: download-only
  90.78 Mbit/s, server latency 44.60 ms. This second remote server result was
  much lower, illustrating that the application results were not consistent
  enough to establish the line's sustained capacity.
- Cloudflare trace confirmed `colo=DUB`, `warp=off`, using both bound WAN
  IPv4 and WAN DHCPv6 source `2a02:8084:2001:6600::f1`. Requests for 100/150 MB
  returned HTTP 403 and are invalid speed tests. A 10 MB request succeeded.
  Four parallel workers making ten 10 MB requests each subsequently received
  mixed HTTP 200/429 responses: both aggregate application tests are invalid
  as full completed benchmarks. However, interface counters over their short
  transfer windows independently measured WAN inbound 464.44 Mbit/s for
  5.63 seconds (IPv4), and 454.75 Mbit/s for 6.01 seconds (IPv6). Corresponding
  LAN background downloads were only 2.13/0.58 Mbit/s. Complete 20-probe ping
  windows spanning these tests had no loss, average RTT about 25 ms, maximum
  101.44 ms (IPv4) and 154.84 ms (IPv6).

Interpretation: direct WAN throughput clearly exceeded 100 Mbit/s and briefly
approached the user's 500 Mbit/s plan. These observations do not certify
sustained 500 Mbit/s service or exclude intermittent ISP/modem congestion.
The upload test ran with the existing 45 Mbit/s WAN shaper enabled, so it is
not an unrestricted measurement of ISP upload capacity. Large-transfer HTTP
errors and rate limiting are test-service responses, not evidence of line
packet loss. See the [updated LAN topology](wifi-ap-mesh-topology.md) for the
confirmed saturated 100 Mbit/s Charles AP uplink, LAN delay observations,
and the user-confirmed MacBook bridge in front of ng-2ndfloor.
