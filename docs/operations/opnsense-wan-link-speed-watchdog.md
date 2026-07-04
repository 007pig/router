# OPNsense WAN Link Speed Watchdog

Date: 2026-07-04

Related current configuration inventory:
[OPNsense Current Non-Default Configuration](opnsense-current-non-default-config.md).

Related modem watchdog:
[OPNsense + Shelly Modem Watchdog](opnsense-shelly-modem-watchdog.md).

This document records the WAN Ethernet link-speed watchdog installed on the
OPNsense router. Its only job is to notify when the physical WAN port stops
negotiating gigabit Ethernet. It does not reboot the modem, call Shelly, alter
gateway monitoring, or change firewall, NAT, or WARP policy.

## Current State

The watchdog is installed and enabled on OPNsense.

OPNsense router:

```sh
ssh root@192.168.1.1
```

Installed script:

```sh
/usr/local/sbin/wan-link-speed-watchdog
```

Repository source copy:

```sh
scripts/opnsense/wan-link-speed-watchdog
```

Installed cron file:

```sh
/usr/local/etc/cron.d/wan-link-speed-watchdog
```

cron schedule:

```text
every minute, as root
```

Notification target:

```text
ntfy server: http://192.168.1.182
ntfy topic: opnsense-alerts
publish URL: http://192.168.1.182/opnsense-alerts
authentication: none
```

Runtime state:

```text
state file: /var/db/wan-link-speed-watchdog.state
test state file: /tmp/wan-link-speed-watchdog.test.state
lock file: /var/run/wan-link-speed-watchdog.lock
log tag: wan-link-speed-watchdog
```

## What Was Changed

A standalone PHP script was installed at:

```sh
/usr/local/sbin/wan-link-speed-watchdog
```

The script monitors:

```text
interface: igc0
expected active media: 1000baseT <full-duplex>
```

The script classifies link state as:

```text
ok:
  status is active and media contains 1000baseT <full-duplex>

degraded:
  status is active but media does not contain 1000baseT <full-duplex>
  example: Ethernet autoselect (100baseTX <full-duplex>)

down:
  status is not active
```

A cron.d file was installed at:

```sh
/usr/local/etc/cron.d/wan-link-speed-watchdog
```

Current cron content:

```cron
SHELL=/bin/sh
PATH=/etc:/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin

*	*	*	*	*	root	/usr/local/sbin/wan-link-speed-watchdog > /dev/null 2>&1
```

cron was restarted after installation:

```sh
/usr/local/sbin/pluginctl -s cron restart
```

The existing modem watchdog was not modified:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Shelly settings, OPNsense gateway monitor settings, WARP policy routing,
firewall rules, and NAT rules were not intentionally changed.

## Runtime Logic

Normal event flow:

```text
cron runs every minute
-> script acquires lock
-> read ifconfig igc0
-> parse media and status
-> classify state as ok, degraded, or down
-> update JSON state file
-> send ntfy only when notification conditions are met
```

Notification behavior:

- First degraded detection sends an ntfy alert.
- Continued degraded state stays quiet for the next minute-to-minute checks.
- Continued degraded state sends a reminder every 3600 seconds.
- Restoring to `1000baseT <full-duplex>` sends a recovery notification.
- Link down is logged as a distinct state but does not send ntfy.
- Normal gigabit state updates the state file and stays quiet.

ntfy alert headers:

```text
degraded:
  Title: OPNsense WAN link degraded
  Priority: high
  Tags: warning,ethernet

restored:
  Title: OPNsense WAN link restored
  Priority: default
  Tags: white_check_mark,ethernet
```

Message body includes:

```text
host
interface
state
status
media
expected media
time
```

Test notifications use the same topic but prefix the title and body with
`[TEST]`.

## Key Parameters

These constants are near the top of the script:

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

The installed script sends ntfy with `/usr/local/bin/curl`. This is intentional:
OPNsense PHP had `allow_url_fopen=0`, so PHP URL streams could not POST to ntfy.

## Validation Results

Validation was run on 2026-07-04.

ntfy health from OPNsense:

```sh
curl -sS --connect-timeout 5 http://192.168.1.182/v1/health
```

Output:

```json
{"healthy":true}
```

Current WAN media:

```text
media: Ethernet autoselect (1000baseT <full-duplex>)
status: active
```

Script syntax check:

```sh
/usr/local/bin/php -l /usr/local/sbin/wan-link-speed-watchdog
```

Output:

```text
No syntax errors detected in /usr/local/sbin/wan-link-speed-watchdog
```

Installed permissions:

```text
-rwxr-xr-x  root wheel  /usr/local/sbin/wan-link-speed-watchdog
-rw-r--r--  root wheel  /usr/local/etc/cron.d/wan-link-speed-watchdog
```

Installed file checksums:

```text
SHA256 (/usr/local/sbin/wan-link-speed-watchdog) = 5c09cf0c9bdb24a5f64a0722e377c9180db46d1a872bca68debb09a0fa6f6b42
SHA256 (/usr/local/etc/cron.d/wan-link-speed-watchdog) = 492ea06f8019b861e2e7d60ee2e7bf71a4eeee74e9d4365c6f01e4bc9946ef51
```

Simulated degraded test:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --reset-test-state \
  --test-media "Ethernet autoselect (100baseTX <full-duplex>)" \
  --test-status active
```

Result:

```text
interface=igc0 state=degraded status=active media=Ethernet autoselect (100baseTX <full-duplex>) source=test
notification sent; state=degraded reason=state-change
```

Immediate repeated degraded test:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --test-media "Ethernet autoselect (100baseTX <full-duplex>)" \
  --test-status active
```

Result:

```text
interface=igc0 state=degraded status=active media=Ethernet autoselect (100baseTX <full-duplex>) source=test
```

No second notification was logged for the immediate repeat.

Hourly reminder test:

The test state `last_notified` timestamp was aged by more than 3600 seconds,
then the same degraded media was tested again.

Result:

```text
interface=igc0 state=degraded status=active media=Ethernet autoselect (100baseTX <full-duplex>) source=test
notification sent; state=degraded reason=reminder
```

Simulated restored test:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --test-media "Ethernet autoselect (1000baseT <full-duplex>)" \
  --test-status active
```

Result:

```text
interface=igc0 state=ok status=active media=Ethernet autoselect (1000baseT <full-duplex>) source=test
notification sent; state=ok reason=restored
```

Simulated link down dry-run:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --dry-run \
  --test-media "Ethernet autoselect (none)" \
  --test-status "no carrier"
```

Result:

```text
interface=igc0 state=down status=no carrier media=Ethernet autoselect (none) source=test
WAN link is not active; interface=igc0 status=no carrier media=Ethernet autoselect (none)
```

Production state after cron verification:

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

The `updated_at` timestamp confirms the cron job ran after cron was restarted.
Normal gigabit state stayed quiet and did not write a new log line every minute.

## Useful Commands

Check current WAN link:

```sh
ifconfig igc0
```

Run the watchdog manually against real state:

```sh
/usr/local/sbin/wan-link-speed-watchdog
```

Check state:

```sh
cat /var/db/wan-link-speed-watchdog.state
```

Check logs:

```sh
grep 'wan-link-speed-watchdog' /var/log/system/latest.log | tail -n 20
```

Check ntfy health:

```sh
curl -sS --connect-timeout 5 http://192.168.1.182/v1/health
```

Syntax-check the script:

```sh
/usr/local/bin/php -l /usr/local/sbin/wan-link-speed-watchdog
```

Check permissions:

```sh
ls -l /usr/local/sbin/wan-link-speed-watchdog /usr/local/etc/cron.d/wan-link-speed-watchdog
```

Restart cron after changing the cron file:

```sh
/usr/local/sbin/pluginctl -s cron restart
```

## Safe Tests

Send a test degraded notification:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --reset-test-state \
  --test-media "Ethernet autoselect (100baseTX <full-duplex>)" \
  --test-status active
```

Send a test restored notification:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --test-media "Ethernet autoselect (1000baseT <full-duplex>)" \
  --test-status active
```

Check test state:

```sh
cat /tmp/wan-link-speed-watchdog.test.state
```

Dry-run a link-down classification without saving state:

```sh
/usr/local/sbin/wan-link-speed-watchdog \
  --dry-run \
  --test-media "Ethernet autoselect (none)" \
  --test-status "no carrier"
```

## Disable Or Re-enable

Temporarily disable scheduled execution without deleting the script:

```sh
mv /usr/local/etc/cron.d/wan-link-speed-watchdog /usr/local/etc/cron.d/wan-link-speed-watchdog.disabled
/usr/local/sbin/pluginctl -s cron restart
```

Re-enable scheduled execution:

```sh
mv /usr/local/etc/cron.d/wan-link-speed-watchdog.disabled /usr/local/etc/cron.d/wan-link-speed-watchdog
/usr/local/sbin/pluginctl -s cron restart
```

Manual runs still work while the cron file is disabled:

```sh
/usr/local/sbin/wan-link-speed-watchdog
```

## Notes

Earlier installation testing briefly used PHP URL streams for ntfy and logged:

```text
ntfy send failed; status=no HTTP response
```

That was caused by OPNsense PHP having `allow_url_fopen=0`. The installed
version uses `/usr/local/bin/curl`, and simulated degraded, reminder, and
restored notifications succeeded after that change.
