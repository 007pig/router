# OPNsense + Shelly Modem Watchdog

The watchdog checks OPNsense's direct IPv4 WAN and can power-cycle the Connect
Box through the Shelly Plug Plus UK on the LAN. The cron deployment replaces
the original gateway-monitor syshook from 2026-06-30. On 2026-11-23 the
IPv4 monitor detected an outage, but OPNsense did not dispatch the routing
alarm that would have called that syshook. See the
[incident investigation](../network/connect-box-ipv4-outage-2026-11-23.md).

## Deployment

- Router script is `/usr/local/sbin/modem-watchdog`, owned by `root:wheel`
  with mode `0755`. [Repository source](../../scripts/opnsense/modem-watchdog)
- Schedule is `/usr/local/etc/cron.d/modem-watchdog`, owned by `root:wheel`
  with mode `0644`. The schedule runs the script every minute as root.
- State is `/var/db/modem-watchdog.json` in live mode and
  `/var/run/modem-watchdog.dry-run.json` in dry-run mode. Both modes share
  `/var/run/modem-watchdog.lock`. Logs use the `modem-watchdog` tag.
- The original script and both executable backup copies were moved out of
  the hook directory into `/conf/modem-watchdog-pre-cron.7zUGwZ0F`.

```cron
SHELL=/bin/sh
PATH=/etc:/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin

* * * * * root /usr/local/sbin/modem-watchdog --live >/dev/null 2>&1
```

For a trial deployment, use `--dry-run` in the cron entry. Dry-run logs the
decision and reads the Shelly relay status, with a separate state file tracking
simulated attempts. After installing or changing the cron file, release the
watchdog lock before running `/usr/local/sbin/pluginctl -s cron restart`
so the cron daemon cannot inherit the lock. Remove the dry-run state when
switching to live mode. The program requires an explicit mode.

## Power-cycle policy

1. Read `WAN_DHCP` through `configctl interface gateways status`. A
   valid `down` or `offline` result must coincide with zero replies to three
   bounded pings to `8.8.8.8`. The route must use `igc0` and the reported
   IPv4 WAN gateway, and the ping binds to the current WAN IPv4 address.
2. Require three adjacent scheduled checks that satisfy both conditions.
   A successful probe, unknown status, manual force-down, latency or loss
   alone, missed run, or router reboot interrupts the count. IPv6,
   WARP, and DNS outcomes do not enter the decision.
3. Check `Switch.GetStatus` on relay 0 at `192.168.1.220`. An unavailable
   relay, output already off, or active timer defers action. Persist an
   attempt before sending `Switch.Set` with `on=false` and
   `toggle_after=20`. Shelly schedules the return to the on state.
4. Allow up to two attempts per outage, at least 900 seconds apart. A
   failed or ambiguous write RPC consumes an attempt. Two adjacent online
   samples clear the per-outage budget. The cooldown and attempt count
   survive an OPNsense restart. On initial migration, an existing valid
   legacy cooldown timestamp is carried forward. Corrupt state or an
   unsuccessful state write prevents action.

## Verification

On 2026-11-23 cron recorded successful dry runs at 17:01 and 17:02 UTC.
The first scheduled live run at 17:03 UTC recorded `WAN_DHCP` online and
zero power-cycle attempts. The mock suite passed on the router's PHP
runtime. Physical relay operation remains to be verified in a maintenance
window.

Run on OPNsense to check the current gateway, independent WAN probe, and
Shelly without saving state or calling `Switch.Set`:

```sh
/usr/local/sbin/modem-watchdog --check
/usr/local/sbin/configctl interface gateways status
grep ' modem-watchdog ' /var/log/system/latest.log | tail -n 15
```

`action=power-cycle-result shelly_outcome=accepted` records an RPC response,
not physical relay or gateway verification. After a real event, check for
its companion `action=power-cycle-start` line, a return to
`output=true` on `Switch.GetStatus`, and fresh gateway samples.

Run the [mock policy tests](../../scripts/opnsense/tests/modem-watchdog.php)
with PHP 8.1 or later. The suite supplies fake Shelly callbacks.

```sh
php scripts/opnsense/tests/modem-watchdog.php
```

## Disable or roll back

Move the cron entry outside `/usr/local/etc/cron.d`, restart cron, and
confirm any in-flight watchdog process has exited. Preserve
`/var/db/modem-watchdog.json` so the attempt limit and cooldown survive
re-enabling. If restoring the legacy deployment, restore the primary
`90-modem-watchdog` script to `/usr/local/etc/rc.syshook.d/monitor/` only
after disabling the cron job. Keep its backup copies outside the hook
directory. The legacy script still requires OPNsense to dispatch a routing
alarm before it can run.

Related [WAN link speed watchdog](opnsense-wan-link-speed-watchdog.md),
[gateway notifications](opnsense-gateway-ntfy-alert.md), and
[Shelly Switch RPC documentation](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Switch/).
