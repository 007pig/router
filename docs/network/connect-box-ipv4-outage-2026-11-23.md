# Connect Box IPv4 outage and missed modem watchdog

Investigated 2026-11-23 after the user manually restarted the Connect Box.
OPNsense timestamps below use Europe/Dublin (UTC on this date). Connect Box
timestamps are as displayed in its Network Log. All device checks were read-only.

## Outage and recovery

| Time | Evidence |
| --- | --- |
| 15:10:36–15:10:37 | OPNsense recorded `WARP_IPV6`, `WARP`, and then `WAN_DHCP` going from loss to down. `WAN_DHCP6` had no concurrent down transition, consistent with the user's observation that native IPv6 was the only working path before the restart. |
| 16:06:25–16:09:54 | OPNsense recorded three WAN Ethernet link drops and recoveries. Native IPv6 monitoring also dropped during this period. |
| 16:09:56 and 16:12:57 | The Connect Box reported DOCSIS T3 ranging timeouts. |
| 16:12:41 | The Connect Box reported `Cable Modem Reboot - HW or Power-On Reset`. |
| 16:13:47 | Both WARP monitors returned to normal. |
| 16:16:18 | Native IPv6 monitoring returned to normal after further loss during recovery. |
| 16:16:55–16:17:09 | The IPv4 monitor went from down to latency, then returned to normal. |
| 16:32 | All four OPNsense gateway monitors were Online with 0% reported loss. The Connect Box status page showed Online / Operational. |

The affected paths and recovery after restart are consistent with an
interruption to IPv4 service through the DS-Lite path. The T3 records show
that the modem missed ranging replies around recovery. The device logs
do not establish whether the original IPv4 outage began in the modem, the
cable path, or the ISP's DS-Lite infrastructure.

The [WAN UDP DNS reply loop](wan-udp-dns-reply-loop-2026-11-23.md) persisted
after gateway recovery. Direct WAN UDP DNS to `1.1.1.1` still timed out in a
three-second probe. A direct WARP query to `1.0.0.1` and one local Unbound
query succeeded. Mac queries to the LAN DNS returned `SERVFAIL` for two
sample names, and HTTPS to one of them failed at name resolution.

## Why the Shelly watchdog did not run

The modem watchdog depends on the OPNsense `monitor` syshook. The
`gateway_watcher.php` running on OPNsense 26.7.9_3 dispatches
`interface routes alarm` only for a state transition that generates a routing
alarm. The dispatch path uses `rc.routing_configure alarm` to call
`rc.syshook monitor`. With default gateway switching disabled and zero
gateway groups configured, the observed transitions generated `MONITOR`
entries only. A read-only call to the installed gateway-group decision
method also returned false for `WAN_DHCP` on `loss -> down` and
`down -> none`. See the [OPNsense watcher source](https://raw.githubusercontent.com/opnsense/core/26.7.9/src/opnsense/scripts/routes/gateway_watcher.php).

The 15:00–16:59 incident window contained 30 `MONITOR` entries and zero
`ALERT` entries as of inspection. There were zero corresponding configd
routing-alarm dispatch entries, zero entries for either custom hook, and no
watchdog cooldown timestamp. The live watchdog was executable, passed PHP
syntax checking, had `DRY_RUN=false`, and still targeted `WAN_DHCP`.
The missing dispatch prevented the watchdog's 90-second debounce and the
Shelly request. A read-only request to Shelly after the incident succeeded and
reported the relay on with about 12 W of load. Its current reachability
does not establish reachability during the outage.

At the time of the investigation, the hook directory also contained two
executable backup copies with `DRY_RUN=true`. The installed `rc.syshook`
enumerates every regular file in the hook directory, including backup
copies. These files could run if routing alarm dispatch resumed.

The replacement cron deployment and the location of the archived scripts
are documented in the [modem watchdog runbook](../operations/opnsense-shelly-modem-watchdog.md).
