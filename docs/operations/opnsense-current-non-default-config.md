# OPNsense Current Non-Default Configuration

Date: 2026-07-01
Last updated: 2026-07-18

This document records the current non-default OPNsense configuration observed
from the router. It is an operational inventory, with dated notes for changes
that materially affect the current operating model.

Sensitive values are intentionally omitted. This includes passwords, private
keys, pre-shared keys, certificates, license data, email/account identifiers,
MAC addresses, and DHCPv6 DUID values.

## Inspection Sources

Sources used on 2026-07-01:

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
- `/usr/local/etc/dnsmasq.conf`
- `/usr/local/sbin/configctl dnsmasq status`
- `/usr/local/sbin/configctl unbound check`
- `/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog`

Additional sources used on 2026-07-04 for the WAN link speed watchdog:

- `/usr/local/sbin/wan-link-speed-watchdog`
- `/usr/local/etc/cron.d/wan-link-speed-watchdog`
- `/var/db/wan-link-speed-watchdog.state`
- `/var/log/system/latest.log`
- `ifconfig igc0`

Additional sources used on 2026-07-04 for the Gateway ntfy alert syshook:

- `/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert`
- `/tmp/gateway-ntfy-alert.test.state`
- `/var/db/gateway-ntfy-alert.state`
- `/var/log/system/latest.log`
- `/usr/local/sbin/configctl interface gateways status`

The initial inventory was read-only. Later on 2026-07-01, LAN DHCPv4 and
DHCPv6 were migrated from ISC DHCP to Dnsmasq DHCP. Router Advertisements stayed
on `radvd`; no modem, WARP, Tailscale, AdGuardHome, Zenarmor, firewall, NAT, or
Shelly settings were intentionally changed as part of the DHCP migration.
After the Dnsmasq migration was validated, `os-isc-dhcp` and its orphaned
`isc-dhcp44-server` dependency were uninstalled.

Later on 2026-07-01 at router UTC time `11:55:00` through `12:06`, the 21
legacy filter rules were migrated to `Firewall -> Rules [new]` using the
OPNsense migration export/import model. The CSV import reported 21 inserted
rules, 0 updated rules, and 0 validation errors. No manual CSV corrections were
needed. After validation, all legacy filter rules were removed. Final rule
counts:

```text
legacy_filter_rules=0
new_filter_rules=21
```

No aliases, NAT, port forwards, DHCP/Dnsmasq, Router Advertisements, WARP,
Tailscale, AdGuardHome, Zenarmor, Connect Box, or Shelly settings were
intentionally changed during the firewall rules migration.

Later on 2026-07-01 at router UTC time `17:50` through `17:55`, a DNS-resolved
host alias named `ChatGPT_WARP_DISABLED` was added and included in
`warp_disabled`. This excludes the exact FQDNs `chatgpt.com`, `cdn.auth0.com`,
and `ws.chatgpt.com` from WARP policy routing for all `warp_hosts` clients.
This is a PF table / DNS-resolved IP exclusion, not HTTP Host or TLS SNI
filtering. Because these services use Cloudflare and CloudFront addresses with
low TTLs, the runtime table contents can change as OPNsense refreshes aliases.
At validation time, `ChatGPT_WARP_DISABLED` and the nested `warp_disabled`
runtime PF tables were populated with the current A/AAAA results. Existing
pre-change ChatGPT/Auth0 WARP states from `warp_hosts` clients were cleared
only for the current `ChatGPT_WARP_DISABLED` destinations so new sessions use
WAN/NAT66.

Later on 2026-07-04 at router UTC time `12:40` through `12:47`, a cron-based
WAN link speed watchdog was installed to notify when physical WAN interface
`igc0` is active but no longer negotiated as `1000baseT <full-duplex>`. The
notification target is the local ntfy server topic
`http://192.168.1.182/opnsense-alerts`. This is a notification-only watchdog:
it does not call Shelly, power-cycle the modem, change gateway monitoring,
modify WARP policy routing, or alter firewall/NAT rules.

Later on 2026-07-04 at router UTC time `13:59` through `14:05`, an OPNsense
Gateway Monitor syshook named `80-gateway-ntfy-alert` was installed to notify
when any affected gateway changes to down/offline or is restored Online. The
notification target is the same local ntfy topic
`http://192.168.1.182/opnsense-alerts`. This is notification-only: it does not
call Shelly, power-cycle the modem, change gateway monitoring, modify WARP
policy routing, or alter firewall/NAT rules.

Later on 2026-07-05 at router UTC time `08:58`, `ChatGPT_WARP_DISABLED`
was extended with `t0.gstatic.com`, `t1.gstatic.com`, `t2.gstatic.com`, and
`t3.gstatic.com`. The preferred wildcard form `*.gstatic.com` was not used
because the current OPNsense `host` alias validation accepts normal FQDNs via
`Util::isDomain()` and does not accept `*` in hostname labels; OPNsense
`isWildcard()` handling applies to IP wildcard/netmask values instead. A
pre-change backup was created at
`/conf/config.xml.pre-chatgpt-warp-disabled-gstatic-20260705-085815`. After
filter reload and alias refresh, the `ChatGPT_WARP_DISABLED` runtime PF table
contained the current `t0` through `t3` `gstatic.com` A/AAAA results, and the
nested `warp_disabled` table also contained those resolved addresses.

Later on 2026-07-06 at router UTC time `16:18`, `ChatGPT_WARP_DISABLED`
was extended with `images.openai.com`. A pre-change backup was created at
`/conf/config.xml.pre-chatgpt-warp-disabled-images-openai-20260706-161857`.
After filter reload and alias refresh, the current `images.openai.com` A/AAAA
results were present in both `ChatGPT_WARP_DISABLED` and nested
`warp_disabled`. Validation-time resolved addresses were `104.18.35.200`,
`172.64.152.56`, `2a06:98c1:3103::6812:23c8`, and
`2a06:98c1:310c::ac40:9838`.

Later on 2026-07-06 at router UTC time `17:08` through `17:29`,
`ChatGPT_WARP_DISABLED` was migrated from a DNS-resolved `host` alias to a
Dnsmasq-managed `external` alias with `expire=86400`. Unbound now forwards
`chatgpt.com`, `cdn.auth0.com`, `gstatic.com`, and `images.openai.com` to
Dnsmasq on `127.0.0.1:53053`; Dnsmasq has managed-alias `ipset` entries for
those domains that populate the external alias from observed DNS answers.
AdGuardHome remains the client-facing listener on TCP/UDP 53 and still forwards
to Unbound on `127.0.0.1:5353`.

During validation, domain-specific Dnsmasq `server=/domain/upstream` lines were
found to prevent reliable `ipset` table population in this setup. The final
configuration therefore sets Dnsmasq `no-resolv` and uses
`/usr/local/etc/dnsmasq.conf.d/codex-chatgpt-managed-alias-upstream.conf` for
global Cloudflare upstreams `1.1.1.1` and `1.0.0.1`. The Dnsmasq domain
overrides intentionally generate only `ipset=` lines. No DNS bypass block,
redirect, DoT block, Connect Box, Shelly, NAT66, WARP interface, or AdGuardHome
filtering-policy changes were made.

Two direct LAN pass rules were added before the WARP policy-routing rules:
`warp_hosts -> ChatGPT_WARP_DISABLED` for IPv4 and IPv6 with no gateway set.
These rules let currently populated managed-alias destinations use the normal
WAN/NAT66 path immediately without waiting for the parent `warp_disabled` table
to be regenerated. After Unbound target-zone cache flushes and clean queries,
returned A/AAAA addresses for `chatgpt.com`, `ws.chatgpt.com`,
`t0.gstatic.com`, and `images.openai.com` were all present in
`ChatGPT_WARP_DISABLED`. Existing PF states matching the populated alias
addresses were cleared narrowly; 37 states were dropped.

Later on 2026-07-18 at router UTC time `13:23` through `13:30`, a Dnsmasq
domain override matching `taobao.com` and all of its subdomain query names was
added to the existing Dnsmasq-managed `ChatGPT_WARP_DISABLED` external alias,
which is nested in `warp_disabled` and already has direct IPv4/IPv6 LAN pass
rules. The existing alias name was retained to avoid changing those firewall
rules. A literal `*.taobao.com` entry was not written because OPNsense host
aliases do not accept `*` in hostname labels. Unbound now forwards the
`taobao.com` zone to Dnsmasq on `127.0.0.1:53053`. No firewall rules, NAT
rules, WARP gateways, or interfaces were changed.

After Dnsmasq, Unbound, the filter, and aliases were reloaded, clean A/AAAA
queries for `taobao.com` and representative subdomain `www.taobao.com`
populated 20 validation-time IPv4/IPv6 destinations. Every returned address
was present in both `ChatGPT_WARP_DISABLED` and the nested `warp_disabled`
runtime PF table. Dnsmasq and Unbound configuration checks passed, and both
services were running.

This remains DNS-resolved IP policy routing rather than hostname or TLS SNI
matching. A deeper validation query for `item.taobao.com` populated its eight
IPv4 destinations in both aliases, but the final IPv6 destinations behind its
two-level external CNAME chain did not enter the managed alias even when the
AAAA query was sent directly to Dnsmasq. Therefore the configured domain
override matches wildcard subdomain queries, but complete traffic exclusion
still depends on Dnsmasq observing and importing each answer. The broader CNAME
target zones `alibabadns.com` and `queniuak.com` were not excluded because that
would affect destinations beyond the requested `taobao.com` namespace.

Migration backups retained on OPNsense:

```text
/conf/codex-dnsmasq-dhcp-migration-20260701-082142/
/conf/config.xml.codex-dnsmasq-dhcp-migration-20260701-082142
/conf/config.xml.codex-pre-model-dnsmasq-dhcp-20260701-084425
/conf/config.xml.codex-pre-isc-dhcp-plugin-uninstall-20260701-114036
/conf/codex-fw-rules-new-migration-20260701-115500/
/conf/config.xml.pre-fw-rules-new-20260701-115500
ZFS snapshot: zroot@pre-fw-rules-new-20260701-115500
/conf/codex-chatgpt-warp-exclusion-20260701-175015/
/conf/config.xml.pre-chatgpt-warp-exclusion-20260701-175015
/conf/config.xml.pre-chatgpt-warp-disabled-gstatic-20260705-085815
/conf/config.xml.pre-chatgpt-warp-disabled-images-openai-20260706-161857
/conf/config.xml.pre-chatgpt-dnsmasq-managed-alias-20260706-170829
/conf/config.xml.pre-chatgpt-dnsmasq-managed-alias-correction-20260706-171044
/conf/config.xml.pre-chatgpt-dnsmasq-managed-alias-global-upstream-20260706-172214
/conf/config.xml.pre-taobao-warp-disabled-20260718-132351
```

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
  query forwarding:
    localdomain -> 127.0.0.1:53053
    1.168.192.in-addr.arpa -> 127.0.0.1:53053
    0.a.f.4.7.4.f.d.d.a.8.c.1.e.d.f.ip6.arpa -> 127.0.0.1:53053
    chatgpt.com -> 127.0.0.1:53053
    cdn.auth0.com -> 127.0.0.1:53053
    gstatic.com -> 127.0.0.1:53053
    images.openai.com -> 127.0.0.1:53053
    taobao.com -> 127.0.0.1:53053
  local zone type: transparent

Dnsmasq:
  enabled: yes
  DHCPv4 listener: UDP 67
  DHCPv6 listener: UDP 547
  DNS connector listener: TCP/UDP 53053
  no-resolv: enabled
  managed-alias upstream include:
    /usr/local/etc/dnsmasq.conf.d/codex-chatgpt-managed-alias-upstream.conf
  Router Advertisements: disabled

DHCPv4 DNS handed to clients:
  192.168.1.1

DHCPv6 DNS handed to clients:
  fde1:c8ad:df47:4fa0::1

System upstream DNS:
  1.1.1.1
  1.0.0.1
```

AdGuardHome remains the client-facing port-53 listener. Unbound remains on port
5353. Dnsmasq is not the primary DNS listener for LAN clients; it is the DHCP
server, a local DNS connector for DHCP-registered names, and the managed-alias
resolver for the WARP exclusion domains forwarded by Unbound.

## DHCPv4 LAN

LAN DHCPv4 is enabled and served by Dnsmasq. ISC DHCPv4 is disabled for LAN.
The `os-isc-dhcp` plugin and `isc-dhcp44-server` package are no longer
installed; rollback to ISC requires reinstalling the plugin first.

```text
range: 192.168.1.10 - 192.168.1.250
gateway: 192.168.1.1
DNS server: 192.168.1.1
static reservations: 20
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

LAN DHCPv6 is enabled and served by Dnsmasq. Router Advertisements remain served
by `radvd`, not Dnsmasq.

```text
range: fde1:c8ad:df47:4fa0::1000 - fde1:c8ad:df47:4fa0::1fff
DNS server: fde1:c8ad:df47:4fa0::1
static reservations: 2
Dnsmasq RA: disabled
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

Post-migration service validation:

```text
dnsmasq is running as pid 60329
unbound is running as pid 60082
radvd is running as pid 83947
dhcp-host entries generated by Dnsmasq: 22
dhcp-range entries generated by Dnsmasq: 2
LAN-tagged dhcp-option entries generated by Dnsmasq: 3
Dnsmasq enable-ra entries: 0
```

DNS validation after migration:

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
  ChatGPT_WARP_DISABLED

ChatGPT_WARP_DISABLED (external):
  expire: 86400
  populated by Dnsmasq managed alias/ipset for:
    chatgpt.com
    cdn.auth0.com
    gstatic.com
    images.openai.com
    taobao.com (root domain and all subdomains)

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

The explicit filter rules are now managed under `Firewall -> Rules [new]`.
Important explicit rules, in effective PF order after the migration:

```text
Rules [new] global/floating:
  pass out IPv4 from WAN_WARP address via WARP gateway
  pass out IPv6 from WAN_WARP address via WARP_IPV6 gateway
  pass logged IPv6 TCP/443 to ADGUARD_HTTPS_V6
  pass logged IPv4 TCP/443 to ADGUARD_HTTPS_V4

WAN:
  block logged direct WAN IPv6 TCP/443 to ADGUARD_HTTPS_V6
  block logged direct WAN IPv4 TCP/443 to ADGUARD_HTTPS_V4
  pass WAN UDP/53 from WAN address with state cap rule label
  pass inbound IPv6 UDP/41641 to WAN address for Tailscale direct connectivity

LAN:
  pass warp_hosts to ChatGPT_WARP_DISABLED without WARP IPv4 gateway
  pass warp_hosts to ChatGPT_WARP_DISABLED without WARP IPv6 gateway
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
stateful filtering: disabled
advertised routes observed 2026-07-04:
  0.0.0.0/0
  ::/0
  192.168.1.0/24
  fd7a:115c:a1e0:b1a:0:7:c0a8:100/120
```

The `fd7a:115c:a1e0:b1a:0:7:c0a8:100/120` route is the Tailscale 4via6
representation of the LAN `192.168.1.0/24` subnet through this subnet router.
MagicDNS names such as `192-168-1-181-via-7` use this path and hairpin through
OPNsense even when the client is already on the LAN.

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
enabled on port 5353 and has DNSSEC enabled. Dnsmasq listens on port 53053 as a
local connector for DHCP-registered names and reverse zones; clients still use
OPNsense on port 53. For managed ChatGPT and Taobao WARP exclusions,
AdGuardHome forwards to Unbound, Unbound forwards the managed domains to
Dnsmasq, and Dnsmasq populates the legacy-named `ChatGPT_WARP_DISABLED`
external alias while using explicit Cloudflare upstreams from the managed
include file.

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
os-sensei
os-sensei-updater
os-sunnyvalley
os-theme-cicada
os-vnstat
```

`os-isc-dhcp` was uninstalled after Dnsmasq DHCP validation. The orphaned
`isc-dhcp44-server` package was also removed. The package removal left the
legacy `dhcpd` user/group present; they are not used by the current Dnsmasq
DHCP service.

## WAN Link Speed Watchdog Cron

The WAN link speed watchdog is installed and executable:

```text
/usr/local/sbin/wan-link-speed-watchdog
repository source: scripts/opnsense/wan-link-speed-watchdog
permissions: -rwxr-xr-x root wheel
sha256: 5c09cf0c9bdb24a5f64a0722e377c9180db46d1a872bca68debb09a0fa6f6b42
```

The cron.d entry is installed:

```text
/usr/local/etc/cron.d/wan-link-speed-watchdog
permissions: -rw-r--r-- root wheel
sha256: 492ea06f8019b861e2e7d60ee2e7bf71a4eeee74e9d4365c6f01e4bc9946ef51
schedule: every minute
```

Current constants:

```php
const LOG_TAG = 'wan-link-speed-watchdog';
const TARGET_INTERFACE = 'igc0';
const EXPECTED_MEDIA = '1000baseT <full-duplex>';
const NTFY_URL = 'http://192.168.1.182/opnsense-alerts';
const STATE_FILE = '/var/db/wan-link-speed-watchdog.state';
const TEST_STATE_FILE = '/tmp/wan-link-speed-watchdog.test.state';
const LOCK_FILE = '/var/run/wan-link-speed-watchdog.lock';
const REMINDER_SECONDS = 3600;
const NTFY_TIMEOUT_SECONDS = 8;
```

Current production state after cron verification on 2026-07-04:

```json
{
    "state": "ok",
    "status": "active",
    "media": "Ethernet autoselect (1000baseT <full-duplex>)",
    "source": "ifconfig",
    "updated_at": "2026-07-04T12:47:00+00:00",
    "last_notified": 0,
    "changed_at": "2026-07-04T12:40:51+00:00"
}
```

Validation sent `[TEST]` degraded, reminder, and restored notifications to
`http://192.168.1.182/opnsense-alerts`. A simulated link-down run only wrote a
log entry. cron was restarted with:

```sh
/usr/local/sbin/pluginctl -s cron restart
```

This watchdog is notification-only and independent of the modem watchdog. See:
[OPNsense WAN Link Speed Watchdog](opnsense-wan-link-speed-watchdog.md).

## Gateway ntfy Alert Syshook

The Gateway Monitor ntfy alert syshook is installed and executable:

```text
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
repository source: scripts/opnsense/gateway-ntfy-alert
permissions: -rwxr-xr-x root wheel
sha256: e6999a96599283b675392107b0577c90fa849baacfdcd84123aa77c87f95a799
```

Current constants:

```php
const LOG_TAG = 'gateway-ntfy-alert';
const NTFY_URL = 'http://192.168.1.182/opnsense-alerts';
const STATE_FILE = '/var/db/gateway-ntfy-alert.state';
const TEST_STATE_FILE = '/tmp/gateway-ntfy-alert.test.state';
const LOCK_FILE = '/var/run/gateway-ntfy-alert.lock';
const CONFIRM_DELAY_SECONDS = 10;
const NTFY_TIMEOUT_SECONDS = 8;
```

Validation on 2026-07-04 confirmed:

```text
ntfy health: {"healthy":true}
real dry-run:
  WAN_DHCP   state=up status=none translated=Online source=configctl
  WAN_DHCP6  state=up status=none translated=Online source=configctl
  WARP       state=up status=none translated=Online source=configctl
  WARP_IPV6  state=up status=none translated=Online source=configctl
production state file: not yet created during dry-run/test-mode validation
test notifications sent:
  [TEST] OPNsense gateway down
  [TEST] OPNsense gateway restored
loss state behavior: logged only, no ntfy notification
```

This syshook is notification-only and independent of the modem watchdog. See:
[OPNsense Gateway ntfy Alert](opnsense-gateway-ntfy-alert.md).

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
5. After LAN clients renew leases from Dnsmasq, verify DHCPv4/v6 lease
   registration, especially DHCPv6 AAAA records for static reservations.
6. Traffic Shaper pipes exist but all matching rules are disabled; decide
   whether those limits should be kept, removed, or re-enabled.
7. SSH root login and password authentication are enabled; keep only if this is
   intentional for the local operational model.

## Related Documents

- [OPNsense IPv6 over DS-Lite with Connect Box](../network/ipv6-dslite-opnsense-connectbox.md)
- [OPNsense Gateway ntfy Alert](opnsense-gateway-ntfy-alert.md)
- [OPNsense WAN Link Speed Watchdog](opnsense-wan-link-speed-watchdog.md)
- [OPNsense + Shelly Modem Watchdog](opnsense-shelly-modem-watchdog.md)
