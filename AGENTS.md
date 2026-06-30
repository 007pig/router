# AGENTS.md

This repository is a local documentation workspace for the home router setup.
It contains operational notes and network diagnostics for OPNsense, the Connect
Box cable modem, WARP routing, and the Shelly modem watchdog.

## First Steps

When working in this repository, start by reading:

```text
docs/README.md
```

Then choose the relevant document:

- IPv6, DS-Lite, Connect Box, WARP, prefix delegation, or LAN IPv6 issues:
  `docs/network/ipv6-dslite-opnsense-connectbox.md`
- Modem power-cycle automation, Shelly Plug, OPNsense gateway monitor syshook,
  or `WAN_DHCP` watchdog behavior:
  `docs/operations/opnsense-shelly-modem-watchdog.md`

Do not assume the current network behavior from memory. Re-read the relevant
document before making a recommendation or changing router/modem state.

## Environment

OPNsense router:

```sh
ssh root@192.168.1.1
```

Connect Box management UI:

```text
http://192.168.0.1/
```

Shelly Plug Plus UK:

```text
http://192.168.1.220/rpc/
```

Use `python3` for Python scripts if any are added or run.

## Safety Rules

- Treat this repository as documentation-first. Prefer documenting findings and
  suggested commands before changing network state.
- Do not change OPNsense, Connect Box, WARP, or Shelly settings unless the user
  explicitly asks for a change.
- Do not click modem/router UI actions that apply, save, reboot, reset, disable
  firewalls, or power-cycle equipment without explicit confirmation.
- Do not expose or record passwords, session tokens, cookies, browser local
  storage, or other credentials in documentation.
- When using Chrome or another browser to inspect router UI, read status pages
  and menus only unless the user explicitly authorizes a configuration change.
- If running commands against OPNsense, distinguish read-only diagnostics from
  commands that modify firewall rules, aliases, services, files, or power state.
- The Shelly can power-cycle the modem. Treat any `Switch.Set` command with
  `on=false` as an outage-causing operation.

## Known Network Context

Current high-level topology:

```text
ISP cable network
-> Connect Box cable modem/router, DS-Lite enabled
-> OPNsense WAN, 192.168.0.150/24
-> OPNsense LAN, 192.168.1.1/24
-> LAN clients
```

Important established findings:

- OPNsense WAN IPv6 works.
- Native OPNsense LAN IPv6 through the Connect Box is not currently usable.
- The Connect Box is in DS-Lite router mode and does not expose a downstream
  IPv6 routed-prefix/static-route/DHCPv6-PD configuration page.
- OPNsense has an intentional rule named
  `Reject non-WARP LAN IPv6 internet (upstream PD not routed)`.
- WARP is the practical IPv6 egress path for selected LAN clients unless the
  upstream routed-prefix issue is fixed.
- There have been stale `2a02:8084:2001:6620::*` IPv6 references in OPNsense
  aliases/DHCPv6 settings. Check the IPv6 document before relying on them.
- The modem watchdog is intentionally tied to `WAN_DHCP` and ignores
  `WAN_DHCP6`.

## Diagnostic Preference

For IPv6 investigations, collect current state in this order:

1. Client IPv6 address and default route.
2. OPNsense interface addresses and IPv6 route table.
3. OPNsense WAN-sourced IPv6 connectivity.
4. OPNsense LAN-prefix-sourced IPv6 connectivity.
5. OPNsense `radvd` and DHCPv6 generated configs.
6. PF rules and relevant aliases such as `Local_Networks` and `warp_hosts`.
7. Connect Box status pages for DS-Lite, WAN IPv6, firewall, and connected
   devices.

Prefer read-only commands such as:

```sh
ifconfig -a
netstat -rn -f inet6
sysctl net.inet6.ip6.forwarding
cat /var/etc/radvd.conf
cat /var/dhcpd/etc/dhcpdv6.conf
pfctl -sr
pfctl -sn
pfctl -t Local_Networks -T show
pfctl -t warp_hosts -T show
```

Use packet capture only with a narrow filter and packet count.

## Documentation Updates

When new findings are made:

- Put network diagnostics under `docs/network/`.
- Put operational runbooks under `docs/operations/`.
- Update the nearest `README.md` index when adding a document.
- Link related documents to each other instead of duplicating long sections.
- Record dates for observations that may change, especially leases, prefixes,
  firmware versions, and gateway state.

