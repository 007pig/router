---
name: opnsense-warp-hosts
description: Manage the OPNsense firewall alias named warp_hosts for LAN clients that should use Cloudflare WARP policy routing. Use when Codex needs to add, remove, list, verify, or document WARP host membership on the home OPNsense router, especially for macOS clients with IPv4 and ULA IPv6 addresses.
---

# OPNsense WARP Hosts

Use this skill to make small, auditable changes to the OPNsense `warp_hosts`
alias. The alias controls which LAN clients match WARP policy-routing and WARP
NAT rules.

## Safety Rules

- Read `docs/README.md` and the relevant WARP/IPv6 document before changing
  router state.
- Treat `warp_hosts` as configuration state. Create or rely on a config backup
  before writing.
- Change only `warp_hosts` unless the user explicitly asks for other router
  changes.
- Do not remove WARP firewall rules, NAT rules, gateways, interfaces, or
  `Reject non-WARP LAN IPv6 internet` as part of host membership changes.
- Verify both configured alias content and the loaded PF table after reloading.

## Script

Use `scripts/manage_warp_hosts.py` from this skill directory.

Common commands from the repository root:

```sh
python3 .agents/skills/opnsense-warp-hosts/scripts/manage_warp_hosts.py list
python3 .agents/skills/opnsense-warp-hosts/scripts/manage_warp_hosts.py add --from-local-macos
python3 .agents/skills/opnsense-warp-hosts/scripts/manage_warp_hosts.py remove --from-local-macos
python3 .agents/skills/opnsense-warp-hosts/scripts/manage_warp_hosts.py add --address 192.168.1.115 --address fde1:c8ad:df47:4fa0::1e35
```

Defaults:

- Router SSH target: `root@192.168.1.1`
- Alias name: `warp_hosts`
- Local macOS interface for discovery: `en0`

The script:

1. Discovers local macOS addresses when `--from-local-macos` is used.
2. Reads the current alias through OPNsense PHP config APIs.
3. Creates `/conf/config.xml.pre-warp-hosts-<timestamp>` before add/remove.
4. Updates only the alias content.
5. Runs `xmllint --noout /conf/config.xml`.
6. Runs `configctl filter reload`.
7. Runs `configctl filter refresh_aliases`.
8. Prints the loaded `pfctl -t warp_hosts -T show` table.

For review-only work, use `--dry-run`; it reads and compares but does not write,
backup, validate, or reload.

## Validation

After add/remove, verify:

```sh
ssh root@192.168.1.1 'pfctl -t warp_hosts -T show'
curl -4 --connect-timeout 8 -sS https://www.cloudflare.com/cdn-cgi/trace
curl -6 --connect-timeout 8 -sS https://www.cloudflare.com/cdn-cgi/trace
```

For a WARP host, new matching flows should report `warp=on` from Cloudflare
trace unless the destination is in `warp_disabled`.
