# Tailscale Subnet Router SSH Diagnostics

Date: 2026-07-04

This records a read-only diagnosis of intermittent SSH disconnects from
`192.168.1.196` to `192-168-1-181-via-7`, compared with stable SSH sessions to
`192-168-1-180-via-7`.

## Context

The client command under test was:

```sh
ssh -t codex@192-168-1-181-via-7 "tmux new -As codex"
```

`192-168-1-181-via-7` is a Tailscale 4via6 MagicDNS name for LAN host
`192.168.1.181` through the OPNsense Tailscale subnet router. For a LAN client
such as `192.168.1.196`, this hairpins traffic through OPNsense instead of
using the direct LAN path:

```text
192.168.1.196
-> Tailscale direct peer path to OPNsense
-> OPNsense tailscaled subnet proxy
-> 192.168.1.1:<ephemeral> to 192.168.1.181:22
```

OPNsense Tailscale state observed during the diagnosis:

```text
tailscale version: 1.98.5
listen port: 41641
advertise exit node: yes
accept subnet routes: no
Tailscale SSH: disabled
disable SNAT: no
stateful filtering: disabled
advertised routes:
  0.0.0.0/0
  ::/0
  192.168.1.0/24
  fd7a:115c:a1e0:b1a:0:7:c0a8:100/120
```

## Observations

- `192.168.1.196` was active in the tailnet and directly connected to OPNsense
  over the LAN ULA path during the failure.
- OPNsense LAN ARP entries for `192.168.1.196`, `192.168.1.181`, and
  `192.168.1.180` were present and normal.
- OPNsense `igc1` interface counters showed no input or output errors during
  the observation window.
- PF had no state table pressure: roughly 2,100 current states versus a hard
  limit of 3,247,000 states. `tcp.established` timeout was 18,000 seconds.
- Repeated short TCP connects from OPNsense to `192.168.1.181:22` and
  `192.168.1.180:22` succeeded.
- Two existing `192-168-1-180-via-7` SSH child sockets remained established
  while the `181` session disconnected.
- A later test using SSH application keepalives stayed connected for a long
  time:

  ```sh
  ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -t codex@192-168-1-181-via-7 "tmux new -As codex"
  ```

At 14:51:11 UTC, a fresh SSH-over-subnet-router child connection to `181`
appeared on OPNsense:

```text
192.168.1.1:48773 -> 192.168.1.181:22 ESTABLISHED
```

At 14:58:31 UTC, when the user reported that the SSH session disconnected,
`tcpdump` on OPNsense `igc1` captured OPNsense sending a reset to `181`:

```text
192.168.1.1.48773 > 192.168.1.181.22: Flags [R.]
```

No corresponding FIN/RST from `192.168.1.181` was captured before that reset.
Afterward, the OPNsense `tailscaled` socket for `192.168.1.181:22` disappeared,
while the `192.168.1.180:22` child sockets remained established.

OPNsense system and filter logs did not show relevant entries. Local
`tailscaled.log*.txt` files under `/var/db/tailscale/` were empty; tailscaled is
configured for remote log collection rather than useful local event logging.

## Interpretation

The observed disconnect was not caused by:

- OPNsense WAN/LAN interface loss.
- Loss of the Tailscale peer path between `192.168.1.196` and OPNsense.
- ARP failure to `192.168.1.181`.
- `192.168.1.181:22` being generally unreachable from OPNsense.
- PF state table pressure or ordinary TCP idle timeout.

The reset seen on the LAN side was emitted by OPNsense/tailscaled toward
`192.168.1.181:22`. In a Tailscale subnet-router flow, this usually means the
subnet proxy closed or aborted the LAN-side child TCP connection after the
corresponding tailnet-side stream was closed/reset, or tailscaled itself aborted
that proxied stream.

Because `192-168-1-180-via-7` stayed up through the same subnet router at the
same time, the problem is specific to the proxied stream for `181`, not the
whole `via-7` subnet route.

The successful `ServerAliveInterval=30` test strongly suggests that idle time
on the proxied SSH stream is part of the trigger. It does not prove which side
of the tailnet-side stream initiates closure, but it makes a pure LAN, ARP, or
target `sshd` availability problem unlikely.

## Practical Guidance

For clients already on `192.168.1.0/24`, prefer direct LAN SSH such as:

```sh
ssh -t codex@192.168.1.181 "tmux new -As codex"
```

Using the `192-168-1-181-via-7` MagicDNS name from a LAN client forces a
hairpin through the OPNsense Tailscale subnet proxy and adds a failure mode that
the direct LAN path does not need.

If the Tailscale `via-7` path must be used, enable SSH application keepalives:

```sh
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -t codex@192-168-1-181-via-7 "tmux new -As codex"
```

For the next deep-dive reproduction, collect these at the same time:

- `ssh -vvv` output on `192.168.1.196`.
- Tailscale client logs on `192.168.1.196`.
- `tailscale debug daemon-logs` on OPNsense.
- OPNsense `tcpdump` on `igc1` for FIN/RST to `192.168.1.181:22`.
