# OPNsense Current Non-Default Configuration

Date: 2026-07-01

This document records the current non-default OPNsense configuration observed
from the router by read-only SSH inspection. It is an operational inventory, not
a change log.

Sensitive values are intentionally omitted. This includes passwords, private
keys, pre-shared keys, certificates, license data, email/account identifiers,
MAC addresses, and DHCPv6 DUID values.

## Inspection Sources

Read-only sources used on 2026-07-01:

```sh
ssh root@192.168.1.1
```

Observed system state:

```text
hostname: router.localdomain
OPNsense: 26.1.10 (amd64), Witty Woodpecker
FreeBSD: 14.3-RELEASE-p15
timezone: Etc/UTC
system DNS: 1.1.1.1, 1.0.0.1
DNS override from WAN: disabled
```

Configuration and runtime sources:

- `/conf/config.xml`
- `ifconfig`
- `netstat -rn -f inet6`
- `/usr/local/sbin/configctl interface gateways status`
- `pfctl -sn`
- `pfctl -sr`
- `pfctl -t <alias> -T show`
- `/var/etc/radvd.conf`
- `/var/dhcpd/etc/dhcpdv6.conf`
- `/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog`

No router, modem, WARP, Tailscale, AdGuardHome, Zenarmor, DHCP, RA, firewall,
NAT, or Shelly settings were changed during this inspection.

## Interface Inventory

Configured interfaces:

```text
WAN:
  OPNsense name: wan
  device: igc0
  IPv4: DHCP
  IPv6: DHCPv6
  DHCPv6 IA-PD length: 4

LAN:
  OPNsense name: lan
  device: igc1
  IPv4: 192.168.1.1/24
  IPv6: fde1:c8ad:df47:4fa0::1/64
  MTU: 1500

TAILSCALE:
  OPNsense name: opt1
  device: tailscale0
  enabled: yes

WAN_WARP:
  OPNsense name: opt2
  device: wg1
  enabled: yes

WireGuard group:
  OPNsense name: wireguard
  enabled: yes
```

Runtime addresses observed:

```text
igc0:
  192.168.0.150/24
  2a02:8084:2001:6600:2f0:cbff:feef:e549/64
  2a02:8084:2001:6600::b3/128

igc1:
  192.168.1.1/24
  fde1:c8ad:df47:4fa0::1/64

wg1:
  172.16.0.2/32
  2606:4700:110:8e08:fe8:72eb:5c58:1336/127

tailscale0:
  100.108.13.119/32
  fd7a:115c:a1e0::f437:d77/48
```

Current IPv6 operating model:

- WAN IPv6 is native through the Connect Box DS-Lite path.
- LAN IPv6 is ULA-only on `fde1:c8ad:df47:4fa0::/64`.
- General LAN IPv6 internet egress uses WAN NAT66.
- WARP policy-routing rules for `warp_hosts` are ordered before general NAT66.
- Native routed downstream LAN IPv6 through the Connect Box remains unusable.

Related background:
[OPNsense IPv6 over DS-Lite with Connect Box](../network/ipv6-dslite-opnsense-connectbox.md).

## Gateways

Configured gateway monitors:

```text
WAN_DHCP:
  interface: wan
  protocol: IPv4
  monitor: 1.1.1.1
  observed state: Online

WAN_DHCP6:
  interface: wan
  protocol: IPv6
  monitor: 2606:4700:4700::1111
  observed state: Online

WARP:
  interface: opt2 / wg1
  protocol: IPv4
  gateway: 172.16.0.1
  monitor: 1.0.0.1
  far gateway: enabled
  observed state: Online

WARP_IPV6:
  interface: opt2 / wg1
  protocol: IPv6
  gateway: 2606:4700:110:8e08:fe8:72eb:5c58:1337
  monitor: 2606:4700:4700::1001
  far gateway: enabled
  observed state: Online
```

The modem watchdog intentionally tracks only `WAN_DHCP`, not `WAN_DHCP6`.

## DNS Services

DNS service layout:

```text
AdGuardHome:
  enabled: yes
  listens on: TCP/UDP 53
  web UI listener observed: TCP 3000

Unbound:
  enabled: yes
  port: 5353
  DNSSEC: enabled
  DHCP registration: enabled
  DHCP static registration: enabled
  local zone type: transparent

DNSMasq:
  not the active LAN DNS listener in the current runtime snapshot

DHCPv4 DNS handed to clients:
  192.168.1.1

DHCPv6 DNS handed to clients:
  fde1:c8ad:df47:4fa0::1

System upstream DNS:
  1.1.1.1
  1.0.0.1
```

AdGuardHome appears to be the port-53 listener, with Unbound on port 5353.
Do not assume Unbound is directly serving LAN clients on port 53 in this
configuration.

## DHCPv4 LAN

LAN DHCPv4 is enabled.

```text
range: 192.168.1.10 - 192.168.1.250
DNS server: 192.168.1.1
```

Static DHCPv4 reservations, with MAC addresses omitted:

```text
Sony-Kitchen          192.168.1.53
ng-groundfloor        192.168.1.101
ng-2ndfloor           192.168.1.102
ng-1stfloor           192.168.1.105
Sony-Livingroom       192.168.1.113
Xiaoyus-MBP           192.168.1.115
wiz_7d40b4            192.168.1.119
Canonedeb17           192.168.1.121
XiaoyuHsiPhone2       192.168.1.133
GS015852              192.168.1.156
docker-dev            192.168.1.176
cryptad-codex-lxc     192.168.1.180
zai-ie                192.168.1.181
hp-pve                192.168.1.200
ShellyPlusPlugUK-1    192.168.1.220
SELPHY                192.168.1.247
EAX12-charles         192.168.1.251
EAX12-2ndfloor        192.168.1.252
EAX12-kitchen         192.168.1.253
EAX12-hall            192.168.1.254
```

## DHCPv6 And Router Advertisements

LAN DHCPv6 is enabled.

```text
range: fde1:c8ad:df47:4fa0::1000 - fde1:c8ad:df47:4fa0::1fff
DNS server: fde1:c8ad:df47:4fa0::1
```

Static DHCPv6 reservations, with DUID values omitted:

```text
Xiaoyus-MBP  fde1:c8ad:df47:4fa0::1e35
[unnamed]    fde1:c8ad:df47:4fa0::1d7d
```

Generated Router Advertisement state:

```text
interface: igc1
mode: assist
prefix: fde1:c8ad:df47:4fa0::/64
AdvManagedFlag: on
AdvOtherConfigFlag: on
AdvAutonomous: on
DeprecatePrefix: off
RDNSS: fde1:c8ad:df47:4fa0::1
DNSSL: localdomain
```

Manage Router Advertisements through OPNsense plugin commands, not raw
`service radvd restart`. See the IPv6 document for the reason and the exact
safe commands.

## Aliases

Current configured firewall aliases:

```text
warp_hosts (host):
  192.168.1.115
  192.168.1.208
  192.168.1.218
  192.168.1.239
  fde1:c8ad:df47:4fa0::14af
  fde1:c8ad:df47:4fa0::169f
  fde1:c8ad:df47:4fa0::1b52
  fde1:c8ad:df47:4fa0::1e35
  fde1:c8ad:df47:4fa0:14da:ddcf:eb93:3105

Local_Networks (network):
  192.168.0.0/16
  10.0.0.0/8
  172.16.0.0/12
  __lan_network
  2606:4700:110:89ed::/64
  2a02:8084:2001:6620::/64
  fde1:c8ad:df47:4fa0::/64
  2a02:8084:2001:6610::/64

Netflix (network):
  52.0.131.132
  3.221.228.214
  18.207.84.236
  54.204.25.0/28
  23.23.189.144/28
  34.195.253.0/25

warp_disabled (network):
  Local_Networks
  Netflix
  Perplexity

Perplexity (host):
  23.22.208.105
  54.90.207.250
  54.242.1.13
  18.208.251.246
  34.230.5.59
  18.207.114.171
  54.221.7.250
  104.22.20.156
  104.22.21.156
  172.67.40.29
  2606:4700:10::ac43:281d
  2606:4700:10::6816:159c
  2606:4700:10::6816:149c

ratelimit_clients (external):
  no inline content in config.xml

ADGUARD_HTTPS_V4 (host):
  94.140.14.15
  94.140.14.16
  94.140.15.16

ADGUARD_HTTPS_V6 (host):
  2a10:50c0::bad1:ff
  2a10:50c0::bad2:ff

NAT66_LAN_V6 (network):
  fde1:c8ad:df47:4fa0::/64
  2a02:8084:2001:6610::/64
```

Notes:

- `2a02:8084:2001:6610::/64` remains in `NAT66_LAN_V6` as a transitional old
  LAN prefix.
- `2a02:8084:2001:6620::/64` remains in `Local_Networks` and should be cleaned
  only after confirming no dependency remains.
- `2606:4700:110:89ed::/64` is currently part of `Local_Networks`; verify its
  dependency before removing or changing it.

## Firewall Policy

Important explicit rules, in effective order from the OPNsense configuration:

```text
Floating:
  pass out IPv4 from WAN_WARP address via WARP gateway
  pass out IPv6 from WAN_WARP address via WARP_IPV6 gateway
  pass logged IPv6 TCP/443 to ADGUARD_HTTPS_V6
  block logged direct WAN IPv6 TCP/443 to ADGUARD_HTTPS_V6
  pass logged IPv4 TCP/443 to ADGUARD_HTTPS_V4
  block logged direct WAN IPv4 TCP/443 to ADGUARD_HTTPS_V4
  pass WAN UDP/53 from WAN address with state cap rule label

LAN:
  pass warp_hosts to !warp_disabled via WARP IPv4 gateway
  pass warp_hosts UDP/443 to !warp_disabled via WARP IPv4 gateway
  pass warp_hosts UDP/80 to !warp_disabled via WARP IPv4 gateway
  pass warp_hosts to !warp_disabled via WARP IPv6 gateway
  pass warp_hosts UDP/80 to !warp_disabled via WARP IPv6 gateway
  pass warp_hosts UDP/443 to !warp_disabled via WARP IPv6 gateway
  pass NAT66_LAN_V6 to !Local_Networks
  reject logged non-WARP LAN IPv6 internet traffic
  pass LAN TCP with configured connection limits
  pass default LAN IPv4 to any
  pass default LAN IPv6 to any

TAILSCALE:
  pass IPv4 from 100.64.0.0/10
  pass IPv6 from fd7a:115c:a1e0::/48

WAN:
  pass inbound IPv6 UDP/41641 to WAN address for Tailscale direct connectivity
```

Operationally important ordering:

- WARP policy-routing rules are before the general LAN NAT66 pass rule.
- The LAN NAT66 pass rule is before
  `Reject non-WARP LAN IPv6 internet (upstream PD not routed)`.
- The default LAN IPv6 allow rule exists, but it is later than the explicit
  WARP/NAT66/reject rules and should not be treated as the primary IPv6 egress
  control.

## NAT And Port Forwarding

Outbound NAT mode:

```text
hybrid
```

Explicit outbound NAT rules:

```text
WARP IPv4:
  interface: WAN_WARP / wg1
  source: warp_hosts
  destination: any

WARP IPv6:
  interface: WAN_WARP / wg1
  source: warp_hosts
  destination: any

Tailscale exit-node IPv4:
  interface: WAN / igc0
  source: 100.64.0.0/10
  destination: any
  description: Codex: Tailscale exit node IPv4 outbound NAT

LAN NAT66:
  interface: WAN / igc0
  source: NAT66_LAN_V6
  destination: any
  description: NAT66 LAN IPv6 to WAN address
```

The loaded PF NAT table confirms:

```text
nat on wg1 inet from <warp_hosts> to any -> (wg1:0)
nat on wg1 inet6 from <warp_hosts> to any -> (wg1:0)
nat on igc0 inet from 100.64.0.0/10 to any -> (igc0:0)
nat on igc0 inet6 from <NAT66_LAN_V6> to any -> (igc0:0)
```

Explicit port forward:

```text
protocol: UDP
external port: 43133
target: 192.168.1.115:43133
configured interfaces: wan, opt2, wireguard
```

PF also generated NAT reflection / hairpin helper rules for the UDP/43133
forward across several local interfaces.

## Static Routes

Current static host routes:

```text
94.140.14.15/32       via WARP       AGH Family v4 via WARP
94.140.14.16/32       via WARP       AGH Family v4 via WARP
94.140.15.16/32       via WARP       AGH Family v4 via WARP
2a10:50c0::bad1:ff/128 via WARP_IPV6 AGH Family v6 via WARP
2a10:50c0::bad2:ff/128 via WARP_IPV6 AGH Family v6 via WARP
```

These routes correspond to the AdGuard Family HTTPS aliases and firewall rules.

## WireGuard WARP

WireGuard is enabled for the WARP tunnel. Private keys and peer keys are not
documented here.

```text
instance name: Wrap
interface: wg1 / WAN_WARP
listen port: 51820
MTU: 1280
tunnel addresses:
  172.16.0.2/32
  2606:4700:110:8e08:fe8:72eb:5c58:1336/127
gateway: 172.16.0.1
routes disabled by instance: yes
configured DNS:
  1.1.1.1
  1.0.0.1
  2606:4700:4700::1111
  2606:4700:4700::1001

peer endpoint:
  162.159.192.1:2408
allowed tunnel address:
  0.0.0.0/0
  ::/0
keepalive: 25
```

WARP egress is controlled by firewall policy-routing rules and outbound NAT,
not by installing default routes from the WireGuard instance.

## Tailscale

Tailscale is enabled.

```text
listen port: 41641
accept DNS from tailnet: no
advertise exit node: yes
accept subnet routes: no
Tailscale SSH: disabled
disable SNAT: no
advertised subnets: none in OPNsense config
```

Runtime listeners:

```text
tailscaled UDP/41641 on IPv4 and IPv6
```

Firewall/NAT support:

- Tailscale tailnet IPv4 `100.64.0.0/10` is allowed inbound on `tailscale0`.
- Tailscale tailnet IPv6 `fd7a:115c:a1e0::/48` is allowed inbound on
  `tailscale0`.
- WAN allows IPv6 UDP/41641 to the WAN address for direct Tailscale connectivity.
- Outbound NAT translates Tailscale exit-node IPv4 traffic from
  `100.64.0.0/10` to the WAN address.

## AdGuardHome, Unbound, And Family Routes

AdGuardHome is enabled and is the observed listener on port 53. Unbound is
enabled on port 5353 and has DNSSEC enabled.

Static routes force AdGuard Family HTTPS destinations through WARP/WARP_IPV6.
Floating firewall rules also pass those HTTPS destinations and block direct WAN
HTTPS to the same destinations.

This is a deliberate policy configuration. Do not remove the routes or aliases
without checking why AdGuard Family traffic was being forced through WARP.

## Zenarmor, Netflow, And Traffic Shaping

Zenarmor:

```text
enabled: yes
observed processes: eastpect, ipdrstreamer
cron job: Zenarmor periodicals, every minute
related sysctls:
  dev.netmap.buf_num=1000000
  dev.netmap.ring_num=1024
  dev.netmap.admode=2
```

Zenarmor license, account, database, and support fields were intentionally not
documented.

Netflow:

```text
collector enabled: yes
capture interfaces: wan
egress-only: wan
version: v9
target: 127.0.0.1:2056
active timeout: 1800
inactive timeout: 15
```

Traffic Shaper:

```text
pipe 10000:
  enabled: yes
  bandwidth: 10 Mbit
  mask: dst-ip
  description: PipeDown

pipe 10001:
  enabled: yes
  bandwidth: 80 Mbit
  mask: dst-ip
  description: PipeDown-CharlesPC-80Mbps
```

All three configured Traffic Shaper rules were disabled at inspection time:

```text
sequence 1: disabled, LAN IPv6 destination 2606:4700:110:89ed::1b52 -> PipeDown
sequence 2: disabled, WAN IPv4 destination 192.168.1.208 -> PipeDown
sequence 3: disabled, WAN IPv4 destination 192.168.1.29 -> PipeDown-CharlesPC-80Mbps
```

The pipes exist, but the current snapshot does not show active shaping rules
using them.

## Management Plane

Web UI:

```text
protocol: HTTPS
configured port: default
alternate hostname: 192-168-1-1-via-7
observed lighttpd listeners: TCP/80 and TCP/443 on IPv4 and IPv6
```

SSH:

```text
enabled: yes
port: 22
group: admins
root login: permitted
password authentication: enabled
observed listeners: TCP/22 on IPv4 and IPv6
```

SSH root login and password authentication are security-sensitive. They are
recorded here as current state, not as a recommendation.

Installed plugin list from the firmware config:

```text
os-adguardhome-maxit
os-isc-dhcp
os-sensei
os-sensei-updater
os-sunnyvalley
os-theme-cicada
os-vnstat
```

## Modem Watchdog Syshook

The modem watchdog is installed and executable:

```text
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
permissions: -rwxr-xr-x root wheel
```

Current constants:

```php
const TARGET_GATEWAY = 'WAN_DHCP';
const SHELLY_IP = '192.168.1.220';
const SHELLY_SWITCH_ID = 0;
const DEBOUNCE_SECONDS = 90;
const SHELLY_OFF_SECONDS = 20;
const COOLDOWN_SECONDS = 900;
const DRY_RUN = false;
const REBOOT_ON_PACKET_LOSS = false;
const LOCK_FILE = '/var/run/modem-watchdog.lock';
const STATE_FILE = '/var/db/modem-watchdog.last-reboot';
```

This confirms the watchdog is live and tied to IPv4 gateway health. See:
[OPNsense + Shelly Modem Watchdog](opnsense-shelly-modem-watchdog.md).

## Follow-Up Items

Configuration items worth revisiting before future cleanup:

1. `NAT66_LAN_V6` still includes transitional
   `2a02:8084:2001:6610::/64`.
2. `Local_Networks` still includes stale
   `2a02:8084:2001:6620::/64`.
3. `Local_Networks` includes `2606:4700:110:89ed::/64`; confirm its dependency
   before removing it.
4. WARP IPv6 ULA entries for devices other than `Xiaoyus-MBP` should be checked
   against actual online client addresses before assuming IPv6 WARP policy is
   complete.
5. Traffic Shaper pipes exist but all matching rules are disabled; decide
   whether those limits should be kept, removed, or re-enabled.
6. SSH root login and password authentication are enabled; keep only if this is
   intentional for the local operational model.

## Related Documents

- [OPNsense IPv6 over DS-Lite with Connect Box](../network/ipv6-dslite-opnsense-connectbox.md)
- [OPNsense + Shelly Modem Watchdog](opnsense-shelly-modem-watchdog.md)
