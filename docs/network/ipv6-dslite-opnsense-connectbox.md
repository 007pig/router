# OPNsense IPv6 over DS-Lite with Connect Box

Date: 2026-06-30
Last updated: 2026-07-01

This document records the IPv6 investigation for the OPNsense router behind a
Virgin/UPC-style Connect Box cable modem using DS-Lite. It summarizes the
observed state, the tests performed, the likely root cause, and the current
NAT66 operating model.

The original 2026-06-30 investigation was read-only. Later sections record the
OPNsense NAT66 changes that were applied after that diagnosis.

## Summary

OPNsense itself has working IPv6 on its WAN side, but LAN clients do not have
working native routed IPv6 through the Connect Box.

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
Box router mode is not currently usable for OPNsense downstream clients.

Current operating model as of 2026-07-01:

- OPNsense LAN IPv6 uses ULA prefix `fde1:c8ad:df47:4fa0::/64`.
- LAN clients can access IPv6-only sites through WAN NAT66.
- NAT66 translates LAN ULA sources to the working OPNsense WAN IPv6 address
  `2a02:8084:2001:6600:2f0:cbff:feef:e549`.
- WARP policy-routing rules for `warp_hosts` remain before the general LAN
  NAT66 rule, so selected WARP devices still have priority.
- This restores outbound IPv6 usability, but not end-to-end native IPv6 or
  inbound IPv6 reachability.

Current full non-default OPNsense configuration inventory:
[OPNsense Current Non-Default Configuration](../operations/opnsense-current-non-default-config.md).

## Current State: Full LAN ULA-only + NAT66

Date applied: 2026-07-01 local session time. OPNsense backup timestamps are in
the router's clock/timezone and were created as `20260630-*`.

Config backups created during implementation:

```text
/conf/config.xml.codex-lan-ula-nat66-20260630-232903
/conf/config.xml.codex-lan-ula-nat66-20260630-233248
```

The second backup was taken immediately before the corrected DHCPv6 static/range
format was written.

Applied OPNsense changes:

- LAN main IPv6 changed from tracked/idassoc6 to static
  `fde1:c8ad:df47:4fa0::1/64`.
- LAN `track6-interface`, `track6-prefix-id`, and `track6_ifid` were removed.
- The previous LAN ULA Virtual IP `fde1:c8ad:df47:4fa0::1/64` was removed
  because that address is now the LAN primary IPv6 address.
- RA mode was set to `assist` with `DeprecatePrefix off`.
- RA RDNSS was set to `fde1:c8ad:df47:4fa0::1`.
- DHCPv6 range was changed to:

  ```text
  fde1:c8ad:df47:4fa0::1000 - fde1:c8ad:df47:4fa0::1fff
  ```

- DHCPv6 DNS was changed to `fde1:c8ad:df47:4fa0::1`.
- DHCPv6 static maps were migrated to ULA:

  ```text
  Xiaoyus-MBP -> fde1:c8ad:df47:4fa0::1e35
  previous 2a02:8084:2001:6620::1d7d -> fde1:c8ad:df47:4fa0::1d7d
  ```

- Alias `NAT66_TEST_CLIENT_V6` was removed.
- Alias `NAT66_LAN_V6` was added:

  ```text
  fde1:c8ad:df47:4fa0::/64
  2a02:8084:2001:6610::/64
  ```

  The `6610::/64` entry is transitional while clients age out old addresses.
  The current Mac had already moved to ULA by the end of verification.

- `Local_Networks` currently loads as:

  ```text
  10.0.0.0/8
  172.16.0.0/12
  192.168.0.0/16
  192.168.1.0/24
  2606:4700:110:89ed::/64
  fde1:c8ad:df47:4fa0::/64
  2a02:8084:2001:6610::/64
  2a02:8084:2001:6620::/64
  ```

  The old `6620::/64` entry was intentionally left in place during this change
  to avoid mixing cleanup with the migration. The `2606:4700:110:89ed::/64`
  entry is also present in the current table and should not be removed without
  first confirming its dependency.

- The single-client LAN rule `TEST allow NAT66 client IPv6 to WAN` was replaced
  by:

  ```text
  Allow LAN IPv6 via WAN NAT66
  ```

- The single-client WAN outbound NAT66 rule was replaced by:

  ```text
  NAT66 LAN IPv6 to WAN address
  ```

Post-apply LAN interface state:

```text
igc1:
  inet 192.168.1.1/24
  inet6 fe80::2f0:cbff:feef:e54a%igc1
  inet6 fde1:c8ad:df47:4fa0::1/64
```

Post-apply IPv6 route table includes:

```text
default -> fe80::b6f2:67ff:fe1a:5545%igc0
fde1:c8ad:df47:4fa0::/64 -> igc1
```

The router still has an old delegated-prefix route:

```text
2a02:8084:2001:6610::/60 -> lo0
```

Do not treat that as usable native LAN IPv6. The active LAN prefix is ULA.

Generated RA config:

```text
interface igc1 {
    AdvSendAdvert on;
    MinRtrAdvInterval 200;
    MaxRtrAdvInterval 600;
    AdvLinkMTU 1500;
    AdvCurHopLimit 64;
    AdvDefaultPreference medium;
    AdvManagedFlag on;
    AdvOtherConfigFlag on;
    RemoveAdvOnExit on;
    prefix fde1:c8ad:df47:4fa0::/64 {
        DeprecatePrefix off;
        AdvOnLink on;
        AdvAutonomous on;
    };
    RDNSS fde1:c8ad:df47:4fa0::1 {
    };
    DNSSL localdomain {
    };
};
```

Current Dnsmasq DHCP config after the 2026-07-01 DHCP migration:

```text
port=53053
interface=igc1
dhcp-range=tag:igc1,192.168.1.10,192.168.1.250,86400
dhcp-range=tag:igc1,::1000,::1fff,constructor:igc1,64,86400
dhcp-option=tag:igc1,3,192.168.1.1
dhcp-option=tag:igc1,6,192.168.1.1
dhcp-option=tag:igc1,option6:23,[fde1:c8ad:df47:4fa0::1]
```

Generated static host reservations were migrated from ISC to Dnsmasq, with MAC
addresses and DHCPv6 DUIDs intentionally omitted from this document. The
generated Dnsmasq config contains 22 `dhcp-host` entries: 20 IPv4 reservations
and 2 DHCPv6 reservations. Dnsmasq Router Advertisements are disabled; RA
remains handled by `radvd`.

Loaded NAT rules include:

```text
nat on wg1 inet6 from <warp_hosts> to any -> (wg1:0) port 1024:65535
nat on igc0 inet6 from <NAT66_LAN_V6> to any -> (igc0:0) port 1024:65535
```

Loaded LAN IPv6 rule order:

```text
pass in quick on igc1 route-to (wg1 2606:4700:110:8e08:fe8:72eb:5c58:1337) inet6 from <warp_hosts> to ! <warp_disabled>
pass in quick on igc1 route-to (wg1 2606:4700:110:8e08:fe8:72eb:5c58:1337) inet6 proto udp from <warp_hosts> to ! <warp_disabled> port = http
pass in quick on igc1 route-to (wg1 2606:4700:110:8e08:fe8:72eb:5c58:1337) inet6 proto udp from <warp_hosts> to ! <warp_disabled> port = https
pass in quick on igc1 inet6 from <NAT66_LAN_V6> to ! <Local_Networks>
block return in log quick on igc1 inet6 from (igc1:network) to ! <Local_Networks>
block return in log quick on igc1 inet6 from fe80::/10 to ! <Local_Networks>
```

This confirms WARP IPv6 policy rules still run before general LAN NAT66.

Loaded aliases:

```text
NAT66_LAN_V6:
  2a02:8084:2001:6610::/64
  fde1:c8ad:df47:4fa0::/64

warp_hosts:
  192.168.1.115
  192.168.1.208
  192.168.1.218
  192.168.1.239
  fde1:c8ad:df47:4fa0::14af
  fde1:c8ad:df47:4fa0::169f
  fde1:c8ad:df47:4fa0::1b52
  fde1:c8ad:df47:4fa0::1e35
  fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105
```

Old `2a02:8084:2001:6620::*` WARP IPv6 entries were removed from
`warp_hosts`. The IPv4 WARP entries were preserved.

Important WARP follow-up: the ULA WARP entries above are reserved intended
addresses. Devices at `192.168.1.208` and `192.168.1.218` were not confirmed
online during the migration. If those devices only use SLAAC and do not take the
reserved DHCPv6 ULA addresses, discover their actual `fde1:*` addresses with
`ndp -an` after they are online and update `warp_hosts`. Until that is verified,
their IPv4 WARP policy remains intact, but their IPv6 WARP priority cannot be
considered fully proven.

Validation:

```sh
xmllint --noout /conf/config.xml
/usr/local/sbin/dnsmasq --test --conf-file=/usr/local/etc/dnsmasq.conf
/usr/local/sbin/configctl dnsmasq status
/usr/local/sbin/configctl unbound check
/usr/local/sbin/pluginctl -s radvd status
```

Observed result:

```text
config.xml valid
dnsmasq: syntax check OK.
dnsmasq is running as pid 60329
no errors in /var/unbound/unbound.conf
radvd is running as pid 83947
```

Client state after RA/DHCPv6 renewal on `Xiaoyus-MBP`:

```text
en0:
  inet 192.168.1.115/24
  inet6 fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105/64 autoconf secured
  inet6 fde1:c8ad:df47:4fa0::1e35/64 dynamic
  default -> fe80::2f0:cbff:feef:e54a%en0
```

Client IPv6-only tests:

```sh
curl -6 --connect-timeout 8 -sS -I https://ipv6.google.com/
curl -6 --connect-timeout 8 -sS -I https://one.one.one.one/
curl -6 --interface fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed result:

```text
HTTP/2 200
```

PF state confirmed NAT66 source translation:

```text
2a02:8084:2001:6600:2f0:cbff:feef:e549 (...) \
  (fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105[54689]) \
  -> 2606:4700:4700::1111[443]
```

Browser verification on `https://test-ipv6.com/`:

```text
Public IPv4: 37.228.238.194
Public IPv6: 2a02:8084:2001:6600:2f0:cbff:feef:e549
IPv6 score: 10/10
```

After the 2026-07-01 Dnsmasq DHCP migration, a direct LAN-client IPv6 HTTPS
test still succeeded:

```sh
curl -6 --connect-timeout 8 -sS -I https://one.one.one.one/
```

Observed result:

```text
HTTP/2 200
```

DNS validation after the DHCP migration:

```text
Dnsmasq 127.0.0.1:53053 resolves Xiaoyus-MBP.localdomain A -> 192.168.1.115
Unbound 127.0.0.1:5353 resolves Xiaoyus-MBP.localdomain A -> 192.168.1.115
AdGuardHome 127.0.0.1:53 resolves Xiaoyus-MBP.localdomain A -> 192.168.1.115
Unknown localdomain names return NXDOMAIN locally.
```

Immediately after cutover, `Xiaoyus-MBP.localdomain` AAAA did not resolve
through Dnsmasq because the client had not yet renewed a DHCPv6 lease from
Dnsmasq. Recheck DHCPv6 dynamic DNS registration after clients renew or
reconnect.

### RA Service Note

Use the OPNsense plugin wrapper for Router Advertisements:

```sh
/usr/local/sbin/pluginctl -c radvd
/usr/local/sbin/pluginctl -s radvd restart
/usr/local/sbin/pluginctl -s radvd status
```

Do not use `service radvd restart` for this setup. During implementation,
`service radvd onerestart` started the FreeBSD package default config:

```text
/usr/local/sbin/radvd -p /var/run/radvd.pid -C /usr/local/etc/radvd.conf
```

That file is an example config and does not advertise LAN `igc1`. The symptom
was that clients kept a ULA address but had no IPv6 default route through LAN.

Correct process after repair:

```text
/usr/local/sbin/radvd -d1 -p /var/run/radvd.pid -C /var/etc/radvd.conf -m syslog
```

If the wrong process is running with the same pidfile, stop it and let OPNsense
start the generated config:

```sh
kill "$(cat /var/run/radvd.pid)"
/usr/local/sbin/pluginctl -c radvd
ps auxww | grep radvd
```

### Rollback From Dnsmasq DHCP Migration

After the later ISC plugin removal, rollback to ISC DHCP requires reinstalling
`os-isc-dhcp` first. Then restore the pre-Dnsmasq backup:

```sh
pkg install -y os-isc-dhcp
cp /conf/config.xml.codex-pre-model-dnsmasq-dhcp-20260701-084425 /conf/config.xml
xmllint --noout /conf/config.xml
/usr/local/sbin/configctl dnsmasq stop
/usr/local/sbin/configctl dhcpd start
/usr/local/sbin/configctl dhcpd6 start
/usr/local/sbin/configctl unbound restart
/usr/local/sbin/pluginctl -c radvd
configctl filter reload
```

Then verify:

```sh
sockstat -46 -l | egrep '(:67|:547|dnsmasq|dhcpd)'
/usr/local/sbin/pluginctl -s dhcpd status
/usr/local/sbin/pluginctl -s dhcpd6 status
/usr/local/sbin/pluginctl -s radvd status
```

### Rollback From Full LAN NAT66

The direct rollback is to restore the backup taken before the full-LAN change:

Note: this rollback target predates the 2026-07-01 Dnsmasq DHCP migration, so
it also returns DHCP service to ISC unless the DHCP migration is reapplied
afterwards.

```sh
cp /conf/config.xml.codex-lan-ula-nat66-20260630-233248 /conf/config.xml
xmllint --noout /conf/config.xml
/usr/local/etc/rc.configure_interface lan
/usr/local/sbin/pluginctl -s dhcpd6 restart
/usr/local/sbin/pluginctl -c radvd
configctl filter reload
```

Then verify:

```sh
ifconfig igc1
netstat -rn -f inet6
cat /var/etc/radvd.conf
cat /var/dhcpd/etc/dhcpdv6.conf
pfctl -sn
pfctl -sr
```

The `dhcpdv6.conf` check above applies only after restoring that historical
pre-Dnsmasq backup. In the current Dnsmasq DHCP state, check
`/usr/local/etc/dnsmasq.conf` instead.

Manual rollback equivalent:

1. Restore LAN IPv6 tracking/idassoc6 settings.
2. Re-add the previous LAN ULA VIP only if returning to the single-client test
   state.
3. Remove `NAT66_LAN_V6`.
4. Remove or disable `Allow LAN IPv6 via WAN NAT66`.
5. Remove or disable `NAT66 LAN IPv6 to WAN address`.
6. Restore any previous DHCPv6 DNS/static-map values only if intentionally
   returning to the pre-migration state.
7. Reload LAN interface, DHCPv6, RA, aliases, and filter.

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

## Initial Local Client State (2026-06-30)

The Mac on the LAN had IPv6 addresses on `en0`, including:

```text
fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105/64
2a02:8084:2001:6620::1e35/64
```

It also had an IPv6 default route via the OPNsense LAN link-local address:

```text
default -> fe80::2f0:cbff:feef:e54a%en0
```

This was internally inconsistent with the diagnosis-time OPNsense LAN prefix,
which was `2a02:8084:2001:6610::/64`. The client address in `6620::/64`
appeared to be a stale or previously reserved prefix, not the then-active routed
LAN prefix.

## Initial OPNsense Interface State (2026-06-30)

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

## Initial OPNsense IPv6 Services (2026-06-30)

`radvd` was running on LAN and advertising the diagnosis-time LAN prefix:

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

## Initial OPNsense Firewall State (2026-06-30)

At diagnosis time, the OPNsense PF rules contained this explicit block before
the later default LAN IPv6 allow rule:

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
upstream routed-prefix problem is fixed, or unless an explicit NAT66/WARP pass
rule has already handled the intended IPv6 egress before this reject rule.

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

Before the ULA-only migration, the `warp_hosts` table contained stale
`6620::*` entries:

```text
192.168.1.208
192.168.1.218
192.168.1.239
2a02:8084:2001:6620::14af
2a02:8084:2001:6620::169f
2a02:8084:2001:6620::1b52
```

After the 2026-07-01 ULA-only migration, the loaded `warp_hosts` table contains
the original IPv4 entries, the tested Mac's IPv4 and current ULA addresses, and
intended ULA reservations:

```text
192.168.1.115
192.168.1.208
192.168.1.218
192.168.1.239
fde1:c8ad:df47:4fa0::14af
fde1:c8ad:df47:4fa0::169f
fde1:c8ad:df47:4fa0::1b52
fde1:c8ad:df47:4fa0::1e35
fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105
```

The Mac that was tested has IPv4 `192.168.1.115`, which was added to
`warp_hosts` on 2026-07-01. Its current LAN ULA addresses
`fde1:c8ad:df47:4fa0::1e35` and
`fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105` were added at the same time so both
IPv4 and IPv6 policy routing can match the client.

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

There are now three verified IPv6 egress states in this history:

- WARP policy routing for selected clients.
- Single-client NAT66 through the working OPNsense WAN IPv6 address.
- Full-LAN ULA-only + WAN NAT66 for general LAN IPv6-only access.

Current recommendation: keep full-LAN ULA-only + WAN NAT66 as the general LAN
IPv6 egress path, and keep WARP policy routing ahead of it for selected
`warp_hosts`. WARP remains the cleaner option when selected clients should use
Cloudflare egress. NAT66 is the better fit when the goal is "LAN clients can
access IPv6-only sites" and the loss of end-to-end IPv6 is acceptable.

Recommended follow-up cleanup steps:

1. Keep `Reject non-WARP LAN IPv6 internet (upstream PD not routed)` enabled
   after the WARP and NAT66 pass rules.
2. Confirm the WARP devices at `192.168.1.208`, `192.168.1.218`, and
   `192.168.1.239` have matching ULA entries in `warp_hosts`, either via
   DHCPv6 reservations or observed SLAAC addresses.
3. Ensure WARP NAT66 on `wg1` remains enabled for `warp_hosts`.
4. After old leases are gone, remove transitional `2a02:8084:2001:6610::/64`
   from `NAT66_LAN_V6` if it is no longer needed.
5. After verifying no dependency remains, remove stale
   `2a02:8084:2001:6620::/64` from `Local_Networks`.
6. Reconnect clients or renew DHCPv6 leases if they still show old GUA
   addresses.
7. Re-test `https://test-ipv6.com/`.

General LAN NAT66 gives usable IPv6, but the external IPv6 address is the
OPNsense WAN IPv6 address, not a LAN client's native IPv6. WARP devices should
show Cloudflare/WARP egress instead.

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
grep -E '^(port=|interface=|dhcp-range=|dhcp-option=|enable-ra)' /usr/local/etc/dnsmasq.conf
```

Check DHCPv6 leases:

```sh
/usr/local/sbin/configctl dnsmasq list leases
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
