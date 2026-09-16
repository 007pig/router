# tank1 NAS LAN / Tailscale access

Date: 2026-09-16. Router: OPNsense `192.168.1.1`; PVE: `192.168.1.200`.

A new unprivileged Debian CT108 `tank1-nas` serves four SMB shares at `192.168.1.187`:
`media`, `downloads`, `shared`, and `backups`. Anonymous users and the optional NAS account
have read/write access. Storage, Samba, snapshot and monitoring details are maintained in the
[PVE runbook](https://github.com/007pig/pve/blob/main/docs/tank1-nas-runbook.md).

## Router change

The candidate address was checked against live config, leases, ARP and ping. The new CT's actual
MAC was used to add a Dnsmasq DHCP reservation plus a local DNS record:
`tank1-nas.localdomain -> 192.168.1.187`. MAC and credentials are omitted here.

`/conf/config.xml` was backed up under `/root/tank1-nas-backups/` before editing. Reconciliation
updates only this CT's mapping and rejects conflicts. No firewall, WAN, WARP, NAT66, DHCP range,
Tailscale policy, route advertisement, or public forwarding rule was changed.

After writing XML, regenerate the runtime template before restarting:

```sh
configctl template reload OPNsense/Dnsmasq
configctl dnsmasq restart
service dnsmasq onestatus
```

A plain service restart initially left the old generated configuration in place. The CT briefly
received a dynamic address; after template generation, its old lease was released and the correct
reservation obtained. The generated dhcp-host, live lease and DNS were checked. Subsequent CT
cold starts retained the correct address.

## Access path

- LAN: `smb://192.168.1.187/shared` or the local DNS name.
- Tailnet: `smb://192-168-1-187-via-7.tailb667d.ts.net/shared` (same pattern for the other shares).
- Public internet: no SMB forward, Funnel or public service was added.

Existing Tailscale 1.102.3 advertises both `192.168.1.0/24` and the site-7 4via6 route. SNAT remains
enabled. Existing TAILSCALE interface rules and tailnet authorization govern entry; Samba sees
the router's LAN-side source. The NAS therefore allows LAN sources without trusting arbitrary
internet users or adding a blanket 100.64.0.0/10 source exception.

The NAS has IPv6 automatic addressing disabled, Samba bound only to IPv4 loopback/LAN TCP445,
and its own nftables source restrictions. It has no separate Tailscale installation.

## Validation

- The via-7 name resolves to its synthesized IPv6 address and routes over the management Mac's
  Tailscale interface. Real SMB file create/read/checksum/rename/delete checks passed through this
  path and separately over LAN, with guest and signed password sessions.
- An isolated test source outside LAN was rejected by the NAS firewall; drop counters increased.
  All temporary test interfaces and namespaces were removed.
- The router has no SMB port-forwarding rule. TCP445 probes from the existing external host to both
  current global WAN IPv6 addresses timed out; this public-edge test is distinct from Tailscale.
- CT106, the Storj HDD, existing VMs/CTs, USB configuration, WARP, modem and router uptime were preserved.

For rollback, remove only the CT108 mapping after shutting down its new sharing service. Do not
restore an entire old config over unrelated concurrent router changes. Preserve all NAS datasets.
