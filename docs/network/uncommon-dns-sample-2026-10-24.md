# Uncommon Domain DNS Sample — 2026-10-24

Tested from the Mac on 2026-10-24 at approximately 14:53–14:56 Europe/Dublin
(13:53–13:56 UTC). The user requested ordinary requests to uncommon domains to
look for failures resembling the earlier riverlight incident.

## Result

31 distinct names were tested: 30 additional names and `riverlight.co.jp` as a
control. System name resolution succeeded for 26. Of these, 25 HTTPS HEAD
requests obtained an HTTP response, including redirects, one HTTP 403, and one
HTTP 503. One other host had a TLS certificate verification failure.

One domain, `sghr.com`, reproduced SERVFAIL and system name-resolution failure.
Its public DNS results also failed, so it does not demonstrate a failure unique
to the Mac, Tailscale, AdGuardHome, or Unbound. No tested name was shown to have
working public address records while persistently failing only through the
local DNS path. The cause of the earlier riverlight failure remains unproven.

## Method and Limits

For each name, the Mac first called the native system resolver using Python
`socket.getaddrinfo()`, then queried A and AAAA through Tailscale DNS
`100.100.100.100`, and finally attempted an HTTPS HEAD request using ordinary
system resolution. No redirects were followed. At most three names were
processed concurrently. DNS probes used one attempt with a three-second query
timeout; HTTPS attempts used a five-second connection timeout and a nine-second
overall limit. Commands had additional process-level timeouts.

Failed native resolution, SERVFAIL, and curl DNS failures triggered immediate
A/AAAA comparisons against `192.168.1.1`, `1.1.1.1`, and `8.8.8.8`. The sghr
failure was then checked directly at Unbound, AdGuardHome, a third public
resolver, and the nameserver addresses supplied by the parent delegation.

These were ordinary diagnostic requests. DNS caches were not flushed and
network settings were not changed. Uncommon names are not guaranteed to be
uncached locally or upstream. Some names selected as candidates had no public
address records and were classified separately. HTTP 403/503 and TLS failures
were not counted as DNS failures. Successful native lookups took 37–1512 ms,
including Python process startup overhead; this is not a pure DNS latency
measurement.

## Captured SERVFAIL: sghr.com

The initial native lookup failed after approximately 10.2 seconds; curl reported
`Could not resolve host`. The results were:

| Resolver or check | Result |
| --- | --- |
| Tailscale `100.100.100.100` | A SERVFAIL; one AAAA empty NOERROR response |
| Router AdGuardHome `192.168.1.1:53` | A and AAAA SERVFAIL |
| Router Unbound `127.0.0.1:5353` | A and AAAA SERVFAIL |
| Cloudflare `1.1.1.1` | A and AAAA SERVFAIL; EDE 22, `at delegation sghr.com.` |
| Quad9 `9.9.9.9` | A SERVFAIL, approximately 4.5 seconds |
| Google `8.8.8.8` | A/AAAA probes timed out; a later A probe also timed out at 8 seconds |

EDE 22 means the resolver could not reach the domain's authoritative
nameservers, or they refused to reply; see [RFC 8914 section 4.23](https://www.rfc-editor.org/rfc/rfc8914.html#section-4.23).
This is diagnostic evidence consistent with an authoritative DNS reachability
problem. A Cloudflare query with checking disabled also timed out; that alone
does not establish a DNSSEC diagnosis.

The `.com` parent delegated the domain to `ns1.hostingnet.com` and
`ns2.hostingnet.com`, supplying IPv4 addresses `52.89.18.51`, `54.152.30.238`,
`18.217.16.210`, and `34.247.146.68`. Direct UDP SOA queries from the Mac to all
four supplied addresses timed out with two-second limits. These are bounded
reachability observations from this network, not proof that the servers are
unreachable from every location.

The newly enabled Unbound failure logging captured the following at
13:54:39 and 13:54:47 UTC:

```text
SERVFAIL <sghr.com. A IN>: all the configured stub or forward servers failed, at zone . upstream server timeout
SERVFAIL <sghr.com. AAAA IN>: all the configured stub or forward servers failed, at zone . upstream server timeout
SERVFAIL <sghr.com. AAAA IN>: all the configured stub or forward servers failed, at zone . from 1.0.0.1 got SERVFAIL
SERVFAIL <sghr.com. A IN>: all the configured stub or forward servers failed, at zone . from 1.0.0.1 got SERVFAIL
```

This demonstrates that failure logging now captures real resolution failures,
beyond the earlier intentional DNSSEC failure test. No DNSSEC validation error
for sghr was observed in the bounded resolver log inspection.

## Other Failed Requests

- `miyazaki-chair.com`, `suzugami.jp`, and `nagatani-en.co.jp`: router,
  Cloudflare, and Google returned NXDOMAIN for the comparisons. These candidates
  did not have resolvable public names at the time of testing.
- `suzugami.jp` initially had one empty AAAA NOERROR response through Tailscale,
  despite A returning NXDOMAIN. A later check through both Tailscale addresses,
  both router addresses, and Cloudflare consistently returned NXDOMAIN. This
  transient response-code discrepancy does not establish an address-resolution
  failure for an otherwise working name.
- `nao.ac.jp`: NOERROR but no A/AAAA records through the router, Cloudflare, and
  Google. `www.nao.ac.jp` resolved and returned HTTP 200 in the second round.
- `tendo-mokko.co.jp`: DNS resolved to `153.123.7.134`; curl rejected the TLS
  certificate as expired. Certificate verification was not bypassed.
- `botanicgardens.ie` returned HTTP 403 and `ill.eu` returned HTTP 503. Both DNS
  lookups and connections succeeded; the HTTP statuses are separate findings.
- `riverlight.co.jp` resolved to `202.254.234.155` and returned HTTP 200.

## Complete Sample

A/AAAA statuses are from explicit Tailscale DNS probes after each native lookup.
`NOERROR` can mean an empty answer; see the classifications above.

| Name | Native resolver | A | AAAA | HTTPS outcome |
| --- | --- | --- | --- | --- |
| `armagh.space` | OK | NOERROR | NOERROR | HTTP 200 |
| `dias.ie` | OK | NOERROR | NOERROR | HTTP 301 |
| `birrcastle.com` | OK | NOERROR | NOERROR | HTTP 200 |
| `botanicgardens.ie` | OK | NOERROR | NOERROR | HTTP 403 |
| `bgs.ac.uk` | OK | NOERROR | NOERROR | HTTP 301 |
| `bas.ac.uk` | OK | NOERROR | NOERROR | HTTP 301 |
| `bto.org` | OK | NOERROR | NOERROR | HTTP 301 |
| `eawag.ch` | OK | NOERROR | NOERROR | HTTP 301 |
| `wsl.ch` | OK | NOERROR | NOERROR | HTTP 301 |
| `esrf.fr` | OK | NOERROR | NOERROR | HTTP 301 |
| `ill.eu` | OK | NOERROR | NOERROR | HTTP 503 |
| `iram-institute.org` | OK | NOERROR | NOERROR | HTTP 200 |
| `senckenberg.de` | OK | NOERROR | NOERROR | HTTP 301 |
| `nhm.uio.no` | OK | NOERROR | NOERROR | HTTP 301 |
| `oigen.jp` | OK | NOERROR | NOERROR | HTTP 200 |
| `iwachu.co.jp` | OK | NOERROR | NOERROR | HTTP 200 |
| `nousaku.co.jp` | OK | NOERROR | NOERROR | HTTP 302 |
| `suzugami.jp` | No address | NXDOMAIN | NOERROR | Could not resolve host |
| `miyazaki-chair.com` | No address | NXDOMAIN | NXDOMAIN | Could not resolve host |
| `nao.ac.jp` | No address | NOERROR | NOERROR | Could not resolve host |
| `riverlight.co.jp` | OK | NOERROR | NOERROR | HTTP 200 |
| `www.nao.ac.jp` | OK | NOERROR | NOERROR | HTTP 200 |
| `miyazakiisu.co.jp` | OK | NOERROR | NOERROR | HTTP 200 |
| `syouryu.com` | OK | NOERROR | NOERROR | HTTP 200 |
| `tendo-mokko.co.jp` | OK | NOERROR | NOERROR | TLS: expired certificate |
| `maruni.com` | OK | NOERROR | NOERROR | HTTP 200 |
| `nissin-mokkou.co.jp` | OK | NOERROR | NOERROR | HTTP 301 |
| `shirakawa.co.jp` | OK | NOERROR | NOERROR | HTTP 301 |
| `sghr.com` | No address | SERVFAIL | NOERROR | Could not resolve host |
| `nagatani-en.co.jp` | No address | NXDOMAIN | NXDOMAIN | Could not resolve host |
| `yoshikin.co.jp` | OK | NOERROR | NOERROR | HTTP 301 |

Related: [riverlight DNS investigation and failure logging setup](riverlight-dns-investigation-2026-10-24.md).
