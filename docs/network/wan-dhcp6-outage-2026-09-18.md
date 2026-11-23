# WAN_DHCP6 100% loss investigation

Observed: 2026-09-18, approximately 08:55–08:59 UTC (09:55–09:59 Europe/Dublin).
All router diagnostics were read-only; no configuration, service, or power changes.

## Finding

WAN native IPv6 connectivity is failing beyond the reachable Connect Box local
gateway. This is a real connectivity failure, not just a gateway dashboard
display issue or failure confined to one ICMP monitoring destination. The
evidence points to Connect Box forwarding or the ISP IPv6/return path, but does
not distinguish those causes. The Connect Box status UI was not inspected in
this session, so its current WAN prefix, uplink route, and event log are unverified.

See [the network operating model](ipv6-dslite-opnsense-connectbox.md) for ULA,
WAN NAT66, WARP, and historical downstream-prefix limitations. This incident
also affects WAN-address-sourced traffic, unlike the historical LAN-prefix issue.

## Evidence

- WAN `igc0` is active at 1000baseT full duplex. Router uptime is 20 days.
- Both WAN addresses remain assigned with positive lifetimes:
  `2a02:8084:2001:6600::b3` and
  `2a02:8084:2001:6600:2f0:cbff:feef:e549`.
- The IPv6 default route and monitor host route use
  `fe80::b6f2:67ff:fe1a:5545%igc0`.
- dpinger binds WAN_DHCP6 to `2a02:8084:2001:6600::b3` and probes
  `2606:4700:4700::1111`.
- Three-packet pings to that monitor failed from each WAN address (100% loss).
  A three-packet ping to Google `2001:4860:4860::8888` from `::b3` also failed.
- IPv6 HTTPS to `https://one.one.one.one/`, bound separately to each WAN
  address, timed out after five seconds.
- Link-local-sourced ping to the Connect Box gateway succeeded 3/3, around
  2 ms. A separate `::b3`-sourced test succeeded 2/3.
- Bounded four-hop traceroute to Google from `::b3` received a first-hop reply
  from `2a02:8084:2001:6600:b6f2:67ff:fe1a:5545`; hops 2–4 timed out.
  Traceroute silence alone does not identify the dropping device.
- A 12-second capture on `igc0`, restricted to ICMPv6 and the monitor address,
  captured 11 outgoing dpinger echo requests to the Connect Box MAC and no
  replies. Thus the probes reach the WAN link; the absence of replies is
  visible before local inbound PF processing.
- Direct IPv4 ping to `1.1.1.1` succeeded 3/3, with RTT 17–102 ms.
- WARP IPv6 ping from its tunnel address to `2606:4700:4700::1001` succeeded
  3/3. That destination has an explicit route through `wg1`.
- LAN ULA, generated radvd/Dnsmasq configuration, and WAN NAT66 rule remain
  present. A router LAN-ULA-sourced ping to Google also failed 3/3; this is not
  a separate end-client NAT66 validation.

Final read-only `gateway_status.php` snapshot:

| Gateway | State | Loss | Delay |
| --- | --- | --- | --- |
| WAN_DHCP6 | Offline | 100.0% | 0.0 ms (no replies) |
| WAN_DHCP | Online | 1.0% | 23.0 ms |
| WARP_IPV6 | Online | 0.0% | 17.6 ms |
| WARP | Online | 0.0% | 17.7 ms |

## Timing

Gateway logs on 2026-09-18 show:

- 03:16:58 UTC: WAN_DHCP6 `none -> loss`, loss 12%.
- 03:17:03 UTC: WAN_DHCP6 `loss -> down`, loss 21%.
- No subsequent WAN_DHCP6 recovery entry was present at inspection.

These correspond to 04:16:58 and 04:17:03 in Ireland. They are alarm transition
times; the actual packet failure began before the moving window crossed its
threshold. IPv4 had brief loss alarms around 08:53–08:54 UTC but was online at
the final snapshot.

## Impact and next diagnostic boundary

General LAN IPv6 using WAN NAT66 is expected to be affected because both WAN
source addresses fail. The WARP IPv6 path remains reachable. Working IPv4 and
WARP mean this is not a complete internet outage.

The next useful read-only checks are the Connect Box WAN IPv6 address/prefix,
default route and event log, plus modem-sourced IPv6 diagnostics if available.
These are needed to distinguish modem forwarding state from ISP routing or
return-path failure. A modem reboot or WAN renewal was not performed.
