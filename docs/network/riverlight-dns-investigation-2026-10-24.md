# riverlight.co.jp Intermittent DNS Failure

Observed: 2026-10-24, approximately 14:40–14:46 Europe/Dublin (13:40–13:46 UTC).
Diagnostics were read-only; no DNS settings, caches, services, firewall rules,
or router state were changed explicitly.

## Finding

The Mac experienced a temporary DNS resolution failure. The domain has a valid
IPv4 address, `202.254.234.155`, and no AAAA record at the authoritative server
tested. DNS resolution and normal HTTPS access recovered during diagnosis.

The router's AdGuardHome query log contains failed and empty responses for this
Mac before the diagnostic queries. This places evidence of the failure in the
router DNS path as well as at the client; it is not sufficient to attribute the
incident to Tailscale alone. The available logs do not establish whether
AdGuardHome, Unbound, its upstream resolver, or an upstream network problem
caused the initial failure.

## Current DNS Path

The Mac's macOS resolver configuration prioritizes Tailscale DNS:

```text
macOS -> Tailscale 100.100.100.100 / fd7a:115c:a1e0::53
      -> OPNsense 192.168.1.1 / fde1:c8ad:df47:4fa0::1
      -> AdGuardHome :53
      -> Unbound 127.0.0.1:5353
      -> Cloudflare 1.1.1.1 / 1.0.0.1
```

`tailscale dns status` confirmed that no tailnet-wide general resolvers were
configured. Tailscale uses the system's router DNS addresses for this domain.
MagicDNS and acceptance of Tailscale DNS were enabled; no exit node was selected.
The installed Tailscale version was `1.104.2`.

This is the configuration observed on this date; older repository notes about
Tailscale DNS preferences should not substitute for this live observation.

## Evidence

- At 14:42:23 local time, a query to `100.100.100.100` returned the correct A
  address but `SERVFAIL` for AAAA. The initial system lookup returned no host
  result, and an ordinary `curl -I https://riverlight.co.jp/` failed with
  `Could not resolve host`.
- Subsequent direct queries to both router DNS addresses, Cloudflare, Google,
  and Quad9 returned the A address. AAAA returned `NOERROR` with no answers and
  an SOA record, which is the expected response when an existing domain has no
  AAAA record.
- Direct queries to Unbound on port 5353 and Dnsmasq on port 53053 also returned
  normal results when tested after the initial failure.
- The authoritative server `ns1.xserver.jp`, queried at `202.226.36.246`, returned
  an authoritative A answer with TTL 86400, and an authoritative empty AAAA
  answer with an SOA record.
- By 14:42:55, Python `socket.getaddrinfo()` resolved the apex and `www` names to
  `202.254.234.155`. Subsequent `dscacheutil` and Tailscale A/AAAA tests succeeded.
- Ordinary HTTPS, IPv4-only HTTPS, and HTTPS with the observed address supplied
  using `curl --resolve` all returned `HTTP/2 200` by approximately 14:43–14:44.

AdGuardHome's existing query log recorded the following four requests at
`2026-10-24T13:40:06.837Z`. The DNS response headers below were decoded from the
logged base64 `Answer` fields, rather than inferred from the query names:

| Query | Client source | Response | Answers / authority |
| --- | --- | --- | --- |
| A | `192.168.1.115` | `SERVFAIL` (RCODE 2) | 0 / 0 |
| A | `fde1:c8ad:df47:4fa0::1e35` | `NOERROR` (RCODE 0) | 0 / 0 |
| AAAA | `fde1:c8ad:df47:4fa0::1e35` | `SERVFAIL` (RCODE 2) | 0 / 0 |
| AAAA | `192.168.1.115` | `NOERROR` (RCODE 0) | 0 / 0 |

All four entries identified upstream `127.0.0.1:5353` and had an empty filtering
`Result` object. They do not show a named blocking rule. In particular, the
empty A answer could not supply an IPv4 address to the client. The logged
upstream label alone does not prove that every final response was passed
through unchanged from Unbound.

The domain-specific log search was limited to the last 10,000–20,000 lines of
the explicit AdGuardHome query-log file. The file was about 2.8 GB; it was not
searched in full. No recursive search of the Unbound chroot was performed.

## Limits and Follow-up

Unbound had `log-servfail: no`, `val-log-level: 0`, and `verbosity: 1`.
Its small daily resolver log contained no corresponding incident details.
Consequently there is no evidence that distinguishes an upstream timeout,
temporary upstream response problem, DNSSEC validation failure, or local
resolver handling for the original requests. There is also no evidence here
that changing WARP routing or disabling Tailscale would fix the underlying
cause.

If this recurs, compare these queries while the failure is still present:

```sh
dig @100.100.100.100 riverlight.co.jp A +time=3 +tries=1
dig @100.100.100.100 riverlight.co.jp AAAA +time=3 +tries=1
dig @192.168.1.1 riverlight.co.jp A +time=3 +tries=1
dig @192.168.1.1 riverlight.co.jp AAAA +time=3 +tries=1
dig @1.1.1.1 riverlight.co.jp A +time=3 +tries=1
dig @1.1.1.1 riverlight.co.jp AAAA +time=3 +tries=1
```

On OPNsense, query Unbound directly using its existing listener:

```sh
drill @127.0.0.1 -p 5353 riverlight.co.jp A
drill @127.0.0.1 -p 5353 riverlight.co.jp AAAA
```

Capture failing responses and relevant existing logs before considering cache
flushes or service restarts. Enabling additional resolver logging would be a
configuration change and was not performed during this investigation.

## Failure Logging Enabled After Investigation

At the user's request, persistent Unbound failure logging was enabled on
2026-10-24 at approximately 14:49 Europe/Dublin (13:49 UTC).

The native OPNsense Unbound model was used to save these settings:

| OPNsense model field | Generated Unbound option | Before | After |
| --- | --- | --- | --- |
| `advanced.logservfail` | `log-servfail` | `no` | `yes` |
| `advanced.valloglevel` | `val-log-level` | `0` | `2` |

`verbosity` remains `1`; `log-queries` and `log-replies` remain `no`.
According to the [Unbound logging documentation](https://unbound.docs.nlnetlabs.nl/en/latest/manpages/unbound.conf.html),
these failure-specific settings record SERVFAIL reasons and detailed DNSSEC
validation failures, including the reason and server supplying invalid data.

A protected pre-change backup is on OPNsense:

```text
/conf/config.xml.pre-unbound-failure-logging-20261024-134849
```

After model validation and saving, the generated configuration was updated and
checked before applying it:

```sh
/usr/local/sbin/configctl template reload OPNsense/Unbound/core
/usr/local/sbin/configctl unbound check
/usr/local/sbin/unbound-control -c /var/unbound/unbound.conf reload_keep_cache
```

The reload retained process PID `35673`. The unchanged cache settings allowed
the cache-preserving reload, and the existing riverlight A record retained its
remaining TTL. Runtime `get_option` checks confirmed both new values. Comparing
the saved configuration with the backup confirmed that only the two logging
settings and normal configuration save metadata changed.

A direct A query for `dnssec-failed.org` returned the expected SERVFAIL and
produced this log entry at `2026-10-24T13:49:21Z`:

```text
validation failure <dnssec-failed.org. A IN>: no keys have a DS with algorithm ECDSAP256SHA256 from 1.0.0.1 for key dnssec-failed.org. while building chain of trust
```

This was an intentional verification query. It does not establish a DNSSEC
cause for the earlier riverlight incident. Normal riverlight A/AAAA checks
through Unbound, the router, and Tailscale remained correct; HTTPS returned 200.

Failure logs are written to the existing OPNsense resolver log. To inspect
recent entries, run on OPNsense using `/bin/sh` for compound commands:

```sh
tail -n 300 /var/log/resolver/latest.log
tail -n 1000 /var/log/resolver/latest.log | grep -i -E 'riverlight|servfail|validation failure'
```

Logs use UTC. To revert this logging change later, set the same two native
model fields to `logservfail=0` and `valloglevel=0`, regenerate and validate the
configuration, then use the same cache-preserving reload. Prefer this targeted
reversal over restoring the whole backup if other configuration has changed.

Related configuration:
[OPNsense Current Non-Default Configuration](../operations/opnsense-current-non-default-config.md#dns-services).

Subsequent testing: [Uncommon Domain DNS Sample (2026-10-24)](uncommon-dns-sample-2026-10-24.md)
tested 31 names, captured a real upstream SERVFAIL for `sghr.com`, and confirmed
that the new failure logging records upstream timeouts and upstream SERVFAIL
responses. Public resolvers also failed for that domain; this does not establish
the cause of the earlier riverlight incident.
