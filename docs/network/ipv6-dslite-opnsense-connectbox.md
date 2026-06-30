# OPNsense IPv6 over DS-Lite with Connect Box

Date: 2026-06-30

This document records the IPv6 investigation for the OPNsense router behind a
Virgin/UPC-style Connect Box cable modem using DS-Lite. It summarizes the
observed state, the tests performed, the likely root cause, and the practical
operating options.

No modem or OPNsense configuration was changed during this investigation.

## Summary

OPNsense itself has working IPv6 on its WAN side, but LAN clients do not have
working native IPv6 through the Connect Box.

The strongest evidence is:

- OPNsense can reach IPv6 internet when using its WAN IPv6 address.
- OPNsense cannot reach IPv6 internet when using its LAN delegated prefix as
  the source address.
- WAN packet capture shows OPNsense sends packets sourced from the LAN prefix
  out through the Connect Box, but no replies come back.
- The Connect Box UI exposes DS-Lite status and IPv6 WAN status, but no
  downstream IPv6 static route, routed prefix, DHCPv6-PD, or router
  advertisement controls.
- OPNsense already has an explicit firewall rule named
  `Reject non-WARP LAN IPv6 internet (upstream PD not routed)`, which blocks
  non-WARP LAN IPv6 internet access before it can time out.

The practical conclusion is that native routed LAN IPv6 through this Connect
Box router mode is not currently usable for OPNsense downstream clients. WARP
remains a stable IPv6 egress option for selected clients. A later single-client
NAT66/ULA test also proved that outbound client access to IPv6-only sites can be
restored by translating selected LAN IPv6 sources to the working OPNsense WAN
IPv6 address.

## Topology

Current network path:

```text
ISP cable network
-> Connect Box cable modem/router, DS-Lite enabled
-> OPNsense WAN, igc0, 192.168.0.150/24
-> OPNsense LAN, igc1, 192.168.1.1/24
-> LAN clients
```

OPNsense access:

```sh
ssh root@192.168.1.1
```

Connect Box management UI:

```text
http://192.168.0.1/
```

## User-visible Symptom

`https://test-ipv6.com/` reported:

```text
No IPv6 address detected
Connections to IPv6-only sites are timing out
Your DNS server appears to have IPv6 Internet access
```

The public IPv4 shown by the test was:

```text
37.228.238.194
```

That IPv4 result is expected to be less useful for this diagnosis because the
connection is DS-Lite. In this setup IPv4 is carried through the ISP DS-Lite
path, while native IPv6 is the primary transport.

## Local Client State

The Mac on the LAN had IPv6 addresses on `en0`, including:

```text
fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105/64
2a02:8084:2001:6620::1e35/64
```

It also had an IPv6 default route via the OPNsense LAN link-local address:

```text
default -> fe80::2f0:cbff:feef:e54a%en0
```

This is internally inconsistent with the current OPNsense LAN prefix, which is
`2a02:8084:2001:6610::/64`. The client address in `6620::/64` appears to be a
stale or previously reserved prefix, not the current routed LAN prefix.

## OPNsense Interface State

WAN interface `igc0`:

```text
description: WAN (wan)
inet 192.168.0.150/24
inet6 2a02:8084:2001:6600:2f0:cbff:feef:e549/64 autoconf
inet6 2a02:8084:2001:6600::b3/128
```

LAN interface `igc1`:

```text
description: LAN (lan)
inet 192.168.1.1/24
inet6 2a02:8084:2001:6610::1/64
```

IPv6 forwarding was enabled:

```text
net.inet6.ip6.forwarding: 1
```

OPNsense IPv6 default route:

```text
default -> fe80::b6f2:67ff:fe1a:5545%igc0
```

## OPNsense IPv6 Services

`radvd` was running on LAN and advertising the current LAN prefix:

```text
interface igc1
prefix 2a02:8084:2001:6610::/64
AdvManagedFlag on
AdvOtherConfigFlag on
AdvAutonomous off
DeprecatePrefix on
```

ISC `dhcpd -6` was running on LAN. The generated DHCPv6 configuration contained:

```text
subnet6 2a02:8084:2001:6610::/64
range6 2a02:8084:2001:6610::1000 2a02:8084:2001:6610::1fff
```

The lease file showed active leases in `2a02:8084:2001:6610::/64`.

There are stale `2a02:8084:2001:6620::*` references that should be cleaned up:

```text
DHCPv6 DNS server: 2a02:8084:2001:6620::1
DHCPv6 static mapping: 2a02:8084:2001:6620::1d7d
warp_hosts alias entries: 2a02:8084:2001:6620::14af, ::169f, ::1b52
Local_Networks alias includes: 2a02:8084:2001:6620::/64
```

Prefer not to use ISP-assigned global IPv6 prefixes in static aliases or DNS
server settings unless the prefix is known to be stable. Use stable IPv4
addresses, MAC/DHCP reservations, ULA, or interface-derived aliases where
possible.

## OPNsense Connectivity Tests

OPNsense WAN-sourced IPv6 works:

```sh
ping6 -c 3 2606:4700:4700::1111
curl -6 --interface 2a02:8084:2001:6600::b3 --connect-timeout 8 -I https://one.one.one.one/
```

Observed result:

```text
ping6: 0.0% packet loss
curl: HTTP/2 200
```

OPNsense LAN-prefix-sourced IPv6 does not work:

```sh
ping6 -S 2a02:8084:2001:6610::1 -c 3 2606:4700:4700::1111
curl -6 --interface 2a02:8084:2001:6610::1 --connect-timeout 8 -I https://one.one.one.one/
```

Observed result:

```text
ping6: 100.0% packet loss
curl: Connection timed out
```

Testing the upstream link-local gateway with the LAN prefix as source also did
not receive replies:

```sh
ping6 -S 2a02:8084:2001:6610::1 -c 3 fe80::b6f2:67ff:fe1a:5545%igc0
```

Observed result:

```text
100.0% packet loss
```

Traceroute from the LAN prefix timed out from the first hop:

```sh
traceroute6 -s 2a02:8084:2001:6610::1 -m 6 2606:4700:4700::1111
```

Observed result:

```text
1  * * *
2  * * *
...
```

WAN capture confirmed OPNsense did send the LAN-prefix-sourced packets out
through `igc0`:

```sh
tcpdump -n -i igc0 -c 3 "ip6 and src host 2a02:8084:2001:6610::1"
```

Observed packets:

```text
2a02:8084:2001:6610::1 > 2606:4700:4700::1111: ICMP6 echo request
```

No replies were observed. This points upstream of OPNsense: the packets leave
OPNsense, but the Connect Box or ISP path does not return traffic for the LAN
prefix.

## OPNsense Firewall State

The OPNsense PF rules contain this explicit block before the later default LAN
IPv6 allow rule:

```text
block return in log quick on igc1 inet6 from (igc1:network) to ! <Local_Networks>
label "ef7e27c757f7826ed572382ef83ed65a"
# Reject non-WARP LAN IPv6 internet (upstream PD not routed)
```

That rule is intentional in the current environment. It prevents LAN clients
from attempting direct native IPv6 internet access through a prefix whose
upstream return path is not working.

The later default allow rule exists but is reached only if earlier quick rules
do not match:

```text
pass in quick on igc1 inet6 from (igc1:network) to any
# Default allow LAN IPv6 to any rule
```

Do not remove or disable the `Reject non-WARP LAN IPv6 internet` rule unless the
upstream routed-prefix problem is fixed, or unless all intended IPv6 egress is
being routed through WARP.

## WARP State

OPNsense has a WARP WireGuard interface:

```text
wg1, description WAN_WARP (opt2)
inet 172.16.0.2/32
inet6 2606:4700:110:8e08:fe8:72eb:5c58:1336/127
```

There are existing NAT and policy-routing rules for `warp_hosts`, including
IPv6 NAT on `wg1`:

```text
nat on wg1 inet6 from <warp_hosts> to any -> (wg1:0)
pass in quick on igc1 route-to (wg1 2606:4700:110:8e08:fe8:72eb:5c58:1337) inet6 from <warp_hosts> to ! <warp_disabled>
```

The current `warp_hosts` table contains:

```text
192.168.1.208
192.168.1.218
192.168.1.239
2a02:8084:2001:6620::14af
2a02:8084:2001:6620::169f
2a02:8084:2001:6620::1b52
```

The Mac that was tested had IPv4 `192.168.1.115`, so it was not covered by the
existing `warp_hosts` IPv4 entries. Its current global IPv6 address was also a
stale `6620` prefix, not the current `6610` LAN prefix.

## Connect Box Findings

The Connect Box UI confirmed DS-Lite:

```text
IPv6 DS-Lite status: Enabled
DS-Lite-FQDN: aftr01.upc.ie
DS-Lite-address: ::
```

Connect Box WAN IPv6 information:

```text
IPv6 address: 2a02:8081:0:40:7903:653b:b27f:2fa3/128
IPv6 default gateway: fe80::217:10ff:feaa:2d88
IPv6 DNS servers: 2001:730:3ec2::11, 2001:730:3ec2::10
```

Connect Box device information:

```text
Standard: DOCSIS 3.0
Hardware version: 5.01
Software version: LG-RDK_CH7465LG-NCIP-6.18-2406.17-NOSH
Config file: CH7465LG_cm_res007_v6.bin
```

Connected devices page showed OPNsense only as a normal IPv4 CPE:

```text
Device name: router
MAC address: 00:F0:CB:EF:E5:49
IP address: 192.168.0.150/24
Speed: 1000 Mbps
Connected to: Ethernet 1
```

The Connect Box UI did not expose:

- Bridge mode or modem-only mode.
- IPv6 static route.
- Downstream routed prefix.
- DHCPv6-PD controls.
- Router Advertisement controls.
- A setting that binds a delegated prefix to the OPNsense CPE.

Security pages:

```text
IPv6 firewall protection: unchecked / disabled when visually verified on 2026-06-30
IPv6 port filtering: No filtering rule applied
```

The modem has no custom IPv6 port filtering rules. The firewall page label text
uses `Enabled` as the checkbox label, but the actual visual state of the IPv6
firewall protection checkbox was unchecked during the follow-up verification.
This makes the Connect Box global IPv6 firewall less likely to be the blocker.
The more likely issue is that the modem or ISP path does not route the
downstream prefix back to OPNsense in router mode.

## Root Cause Assessment

The likely root cause is not DNS and not lack of IPv6 on the ISP connection.

The failure is between the Connect Box and OPNsense LAN prefix:

```text
LAN client
-> OPNsense LAN prefix 2a02:8084:2001:6610::/64
-> OPNsense WAN
-> Connect Box
-> ISP
<- reply traffic is not delivered back to OPNsense LAN prefix
```

Because OPNsense can send packets sourced from the LAN prefix out of its WAN
interface, the local OPNsense routing table is not the immediate blocker.
Because no replies come back, the Connect Box or ISP upstream is not routing or
allowing the downstream prefix correctly.

The Connect Box is not in bridge mode and does not expose a static IPv6 route or
downstream PD management page. That makes native OPNsense-managed LAN IPv6
unreliable in this topology.

## Recommended Operating Model

There are now two verified IPv6 egress models:

- WARP policy routing for selected clients.
- Single-client NAT66 through the working OPNsense WAN IPv6 address.

WARP remains the cleaner option when selected clients should use Cloudflare
egress. NAT66 is the better fit when the immediate goal is only "this LAN
client can access IPv6-only sites" and the loss of end-to-end IPv6 is
acceptable.

Recommended WARP cleanup steps:

1. Keep `Reject non-WARP LAN IPv6 internet (upstream PD not routed)` enabled.
2. Put clients that need IPv6 internet into `warp_hosts` using stable IPv4 DHCP
   reservations, not changing ISP global IPv6 addresses.
3. Ensure WARP NAT66 on `wg1` remains enabled for `warp_hosts`.
4. Remove or replace stale `2a02:8084:2001:6620::*` entries in aliases and
   DHCPv6 static mappings.
5. Change DHCPv6 DNS from the stale `2a02:8084:2001:6620::1` to a stable value.
   Prefer ULA or IPv4 DNS if the ISP global prefix changes.
6. Reconnect clients or renew DHCPv6 leases.
7. Re-test `https://test-ipv6.com/`.

This gives usable IPv6, but the external IPv6 address will be WARP/Cloudflare,
not the ISP native IPv6 prefix.

## NAT66 / ULA Single-Client Test

Date applied: 2026-06-30

Goal: restore outbound IPv6 access for the test Mac only, without changing the
Connect Box and without making all LAN clients use direct IPv6.

OPNsense config backup created before the change:

```text
/conf/config.xml.codex-nat66-test-20260630-230205
```

Applied OPNsense changes:

- Added LAN IP Alias `fde1:c8ad:df47:4fa0::1/64` on `igc1`.
- Added alias `NAT66_TEST_CLIENT_V6` with:

  ```text
  2a02:8084:2001:6610::1e35
  fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105
  ```

- Added `fde1:c8ad:df47:4fa0::/64` to `Local_Networks`.
- Added LAN IPv6 pass rule immediately before the non-WARP IPv6 reject rule:

  ```text
  TEST allow NAT66 client IPv6 to WAN
  ```

- Added WAN outbound NAT66 rule:

  ```text
  TEST NAT66 selected LAN IPv6 to WAN address
  ```

Post-apply checks:

```text
igc1 has inet6 fde1:c8ad:df47:4fa0::1/64
route table has fde1:c8ad:df47:4fa0::/64 on igc1
nat on igc0 inet6 from <NAT66_TEST_CLIENT_V6> to any -> (igc0:0)
pass in quick on igc1 inet6 from <NAT66_TEST_CLIENT_V6> to ! <Local_Networks>
```

The LAN pass rule is loaded before the existing block:

```text
pass in quick on igc1 inet6 from <NAT66_TEST_CLIENT_V6> to ! <Local_Networks>
block return in log quick on igc1 inet6 from (igc1:network) to ! <Local_Networks>
```

Client-side tests from the Mac succeeded:

```sh
curl -6 --connect-timeout 8 -sS -I https://ipv6.google.com/
curl -6 --connect-timeout 8 -sS -I https://one.one.one.one/
curl -6 --interface fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed result:

```text
HTTP/2 200
```

WAN capture for a forced ULA-source HTTPS request to Google showed NAT66 source
translation to the OPNsense WAN SLAAC address:

```text
2a02:8084:2001:6600:2f0:cbff:feef:e549 > 2a00:1450:400b:c01::71.443
```

The original ULA source was:

```text
fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105
```

Chrome browser verification on `https://test-ipv6.com/` succeeded:

```text
Public IPv6 address: 2a02:8084:2001:6600:2f0:cbff:feef:e549
IPv6 score: 10/10
```

Interpretation: NAT66 is a viable workaround for the stated goal, which is
client access to IPv6-only sites. It does not restore end-to-end native IPv6 and
does not provide inbound IPv6 reachability to LAN clients.

Rollback for this test:

1. Disable or delete outbound NAT rule
   `TEST NAT66 selected LAN IPv6 to WAN address`.
2. Disable or delete LAN firewall rule `TEST allow NAT66 client IPv6 to WAN`.
3. Remove `fde1:c8ad:df47:4fa0::/64` from `Local_Networks`.
4. Delete alias `NAT66_TEST_CLIENT_V6`.
5. Delete LAN IP Alias `fde1:c8ad:df47:4fa0::1/64`.
6. Reload VIPs and firewall, then verify:

   ```sh
   ifconfig igc1
   pfctl -sn
   pfctl -sr
   netstat -rn -f inet6
   ```

## Optional Verification Test

The only Connect Box setting that may influence this is `IPv6 firewall`.

A controlled test would be:

1. Temporarily disable Connect Box IPv6 firewall protection.
2. Immediately test from OPNsense:

   ```sh
   ping6 -S 2a02:8084:2001:6610::1 -c 3 2606:4700:4700::1111
   curl -6 --interface 2a02:8084:2001:6610::1 --connect-timeout 8 -I https://one.one.one.one/
   ```

3. Restore the previous Connect Box IPv6 firewall setting.

Interpretation:

- If the test starts working, Connect Box IPv6 firewall is blocking return
  traffic for the downstream prefix.
- If the test still fails, the Connect Box or ISP simply does not route the
  downstream prefix to OPNsense in router mode.

This test changes modem firewall behavior and should be done only intentionally.

### Verification Result: 2026-06-30

The Connect Box firewall page was rechecked after logging in. The `IPv6
firewall -> Firewall protection` checkbox was already unchecked, and the `Apply
changes` button was disabled. No Connect Box setting was changed and no restore
action was needed.

In that current unchecked state, OPNsense still could not use the LAN delegated
prefix as an IPv6 source for HTTPS:

```sh
curl -6 --interface 2a02:8084:2001:6610::1 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed result:

```text
curl: (28) Connection timed out after 8030 milliseconds
```

The WAN IPv6 source still worked as a control:

```sh
curl -6 --interface 2a02:8084:2001:6600::b3 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed result:

```text
HTTP/2 200
```

ICMP commands were not completed in this follow-up pass due to command approval
tooling failure, but earlier ICMP tests already showed the same pattern:
WAN-sourced IPv6 worked and LAN-prefix-sourced IPv6 timed out.

Conclusion: disabling the visible Connect Box IPv6 firewall protection is not
sufficient to make the downstream OPNsense LAN prefix routable. The root cause
remains upstream prefix routing or Connect Box router-mode behavior, not a
simple enabled IPv6 firewall checkbox.

### Neighbor Discovery Capture: 2026-06-30

To check whether an NDP proxy or IPv6 passthrough workaround is likely to help,
OPNsense WAN `igc0` was monitored for ICMPv6 Neighbor Solicitation and Neighbor
Advertisement packets while a second SSH session triggered LAN-prefix-sourced
IPv6 traffic.

Capture command:

```sh
tcpdump -n -i igc0 -c 40 'icmp6 and (ip6[40] == 135 or ip6[40] == 136)'
```

Traffic trigger, run twice:

```sh
curl -6 --interface 2a02:8084:2001:6610::1 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed trigger results:

```text
curl: (28) Connection timed out after 8014 milliseconds
curl: (28) Connection timed out after 8008 milliseconds
```

No matching ICMPv6 Neighbor Solicitation or Neighbor Advertisement packets were
observed on `igc0` during the two attempts. The capture was stopped manually
after the second timeout.

Interpretation: during this test, the Connect Box did not visibly try to resolve
the OPNsense LAN-prefix address on the WAN-side Ethernet segment. That makes an
OPNsense-side NDP proxy/relay workaround less promising. It does not prove
whether reply traffic is dropped by the ISP before reaching the Connect Box or
by the Connect Box itself, but it provides no evidence that the Connect Box is
waiting for OPNsense to answer neighbor discovery for `2a02:8084:2001:6610::/64`.

## Do Not Do

- Do not remove the OPNsense non-WARP LAN IPv6 block until upstream return
  routing is known to work.
- Do not rely on stale `2a02:8084:2001:6620::*` addresses.
- Do not use changing ISP global IPv6 prefixes as long-term alias keys.
- Do not treat `WAN_DHCP6` being online as proof that IPv4 or DS-Lite is healthy.
  This is also why the modem watchdog tracks `WAN_DHCP` separately.

## Useful Commands

Check OPNsense IPv6 interfaces:

```sh
ifconfig -a
```

Check IPv6 routes:

```sh
netstat -rn -f inet6
```

Check forwarding:

```sh
sysctl net.inet6.ip6.forwarding
```

Check generated RA config:

```sh
cat /var/etc/radvd.conf
```

Check generated DHCPv6 config:

```sh
cat /var/dhcpd/etc/dhcpdv6.conf
```

Check DHCPv6 leases:

```sh
tail -n 160 /var/dhcpd/var/db/dhcpd6.leases
```

Test WAN-sourced IPv6:

```sh
ping6 -c 3 2606:4700:4700::1111
curl -6 --interface 2a02:8084:2001:6600::b3 --connect-timeout 8 -I https://one.one.one.one/
```

Test LAN-prefix-sourced IPv6:

```sh
ping6 -S 2a02:8084:2001:6610::1 -c 3 2606:4700:4700::1111
curl -6 --interface 2a02:8084:2001:6610::1 --connect-timeout 8 -I https://one.one.one.one/
```

Capture LAN-prefix-sourced packets on OPNsense WAN:

```sh
tcpdump -n -i igc0 -c 3 "ip6 and src host 2a02:8084:2001:6610::1"
```

Capture IPv6 neighbor discovery on OPNsense WAN:

```sh
tcpdump -n -i igc0 -c 40 'icmp6 and (ip6[40] == 135 or ip6[40] == 136)'
```

Inspect OPNsense PF rules:

```sh
pfctl -sr
pfctl -sn
pfctl -t Local_Networks -T show
pfctl -t warp_hosts -T show
```

## Related Documents

- [OPNsense + Shelly Modem Watchdog](../operations/opnsense-shelly-modem-watchdog.md)
