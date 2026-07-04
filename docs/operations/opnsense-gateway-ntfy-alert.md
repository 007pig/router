# OPNsense Gateway ntfy Alert

Date: 2026-07-04

Related current configuration inventory:
[OPNsense Current Non-Default Configuration](opnsense-current-non-default-config.md).

Related modem watchdog:
[OPNsense + Shelly Modem Watchdog](opnsense-shelly-modem-watchdog.md).

Related WAN physical-link watchdog:
[OPNsense WAN Link Speed Watchdog](opnsense-wan-link-speed-watchdog.md).

This document records the notification-only OPNsense Gateway Monitor syshook
that sends ntfy alerts when any monitored gateway goes down or is restored. It
does not reboot the modem, call Shelly, alter gateway monitoring, or change
firewall, NAT, or WARP policy.

## Current State

The syshook is installed and enabled on OPNsense.

OPNsense router:

```sh
ssh root@192.168.1.1
```

Installed syshook:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Repository source copy:

```sh
scripts/opnsense/gateway-ntfy-alert
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
state file: /var/db/gateway-ntfy-alert.state
test state file: /tmp/gateway-ntfy-alert.test.state
lock file: /var/run/gateway-ntfy-alert.lock
log tag: gateway-ntfy-alert
confirmation delay: 10 seconds
```

## What Was Changed

A standalone PHP syshook was installed at:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

The script runs when OPNsense Gateway Monitor invokes the `monitor` syshook. It
accepts the affected gateway list passed by OPNsense, waits 10 seconds, then
re-reads current gateway state before deciding whether to notify.

The script monitors all Gateway Monitor managed gateways passed to the syshook.
Current configured gateways are:

```text
WAN_DHCP
WAN_DHCP6
WARP
WARP_IPV6
```

Classification:

```text
down:
  status is offline or contains down

up:
  status is none or status_translated is Online

other:
  packet loss, delay, or any non-Online state that is not down/offline
```

Only `down` and `up` state transitions send ntfy notifications. Packet-loss and
delay states are logged but do not send notifications and do not clear a
previous down state.

The existing modem watchdog was not modified:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Shelly settings, OPNsense gateway monitor settings, WARP policy routing,
firewall rules, and NAT rules were not intentionally changed.

## Runtime Logic

Normal event flow:

```text
Gateway Monitor changes state
-> OPNsense runs monitor syshook scripts
-> 80-gateway-ntfy-alert receives affected gateway names
-> acquire lock
-> wait 10 seconds
-> read current gateway status
-> classify each affected gateway as down, up, or other
-> compare with JSON state file
-> send ntfy only for first down or restored-from-down
-> update JSON state file
```

Notification behavior:

- First confirmed down state for a gateway sends a down alert.
- Continued down state for the same gateway stays quiet.
- Restored Online state sends a recovery alert only if the previous recorded
  state was down.
- First observed Online state after installation stays quiet.
- Packet loss and delay are logged but do not send ntfy.

ntfy alert headers:

```text
down:
  Title: OPNsense gateway down
  Priority: high
  Tags: warning,router

restored:
  Title: OPNsense gateway restored
  Priority: default
  Tags: white_check_mark,router
```

Message body includes:

```text
host
gateway
state
status
status_translated
address
monitor
loss
delay
source
time
```

Test notifications use the same topic but prefix the title and body with
`[TEST]`.

## Key Parameters

These constants are near the top of the script:

```php
const LOG_TAG = 'gateway-ntfy-alert';
const NTFY_URL = 'http://192.168.1.182/opnsense-alerts';
const STATE_FILE = '/var/db/gateway-ntfy-alert.state';
const TEST_STATE_FILE = '/tmp/gateway-ntfy-alert.test.state';
const LOCK_FILE = '/var/run/gateway-ntfy-alert.lock';
const CONFIRM_DELAY_SECONDS = 10;
const NTFY_TIMEOUT_SECONDS = 8;
```

The installed script sends ntfy with `/usr/local/bin/curl`, matching the WAN
link speed watchdog pattern.

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

Script syntax check:

```sh
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Output:

```text
No syntax errors detected in /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Installed permissions:

```text
-rwxr-xr-x  root wheel  /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
-rwxr-xr-x  root wheel  /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Installed file checksum:

```text
SHA256 (/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert) = e6999a96599283b675392107b0577c90fa849baacfdcd84123aa77c87f95a799
```

Current real gateway dry-run:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --dry-run \
  --confirm-delay=0 \
  --affected=WAN_DHCP,WAN_DHCP6,WARP,WARP_IPV6
```

Output:

```text
gateway=WAN_DHCP state=up status=none translated=Online source=configctl
gateway=WAN_DHCP6 state=up status=none translated=Online source=configctl
gateway=WARP state=up status=none translated=Online source=configctl
gateway=WARP_IPV6 state=up status=none translated=Online source=configctl
```

The dry-run did not send real notifications and did not create
`/var/db/gateway-ntfy-alert.state`.

Simulated down test:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --confirm-delay=0 \
  --reset-test-state \
  --test-gateway=WAN_DHCP \
  --test-status=down \
  --test-status-translated=Offline \
  --test-address=192.168.0.1 \
  --test-monitor=1.1.1.1 \
  --test-loss=100pct \
  --test-delay=0ms
```

Result:

```text
gateway=WAN_DHCP state=down status=down translated=Offline source=test
notification sent; gateway=WAN_DHCP state=down reason=state-change status=down
```

Repeated down test:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --confirm-delay=0 \
  --test-gateway=WAN_DHCP \
  --test-status=down \
  --test-status-translated=Offline
```

Result:

```text
gateway=WAN_DHCP state=down status=down translated=Offline source=test
```

No second `notification sent` log was written.

Loss-state boundary test:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --confirm-delay=0 \
  --test-gateway=WAN_DHCP \
  --test-status=loss \
  --test-status-translated=PacketLoss \
  --test-loss=25pct \
  --test-delay=35ms
```

Result:

```text
gateway=WAN_DHCP state=other status=loss translated=PacketLoss source=test
gateway state is not down/up; gateway=WAN_DHCP status=loss translated=PacketLoss loss=25pct delay=35ms source=test
```

The loss state did not send ntfy and did not clear the previous test down state.

Simulated restored test:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --confirm-delay=0 \
  --test-gateway=WAN_DHCP \
  --test-status=none \
  --test-status-translated=Online \
  --test-address=192.168.0.1 \
  --test-monitor=1.1.1.1 \
  --test-loss=0pct \
  --test-delay=20ms
```

Result:

```text
gateway=WAN_DHCP state=up status=none translated=Online source=test
notification sent; gateway=WAN_DHCP state=up reason=restored status=none
```

Test state after restored:

```json
{
    "WAN_DHCP": {
        "state": "up",
        "status": "none",
        "status_translated": "Online",
        "address": "192.168.0.1",
        "monitor": "1.1.1.1",
        "loss": "0pct",
        "delay": "20ms",
        "source": "test",
        "updated_at": "2026-07-04T14:05:35+00:00",
        "changed_at": "2026-07-04T14:05:35+00:00",
        "last_notified": 1783173935
    }
}
```

## Useful Commands

Check current OPNsense gateway status:

```sh
/usr/local/sbin/configctl interface gateways status
```

Run dry-run against current real gateway state:

```sh
/usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert \
  --dry-run \
  --confirm-delay=0 \
  --affected=WAN_DHCP,WAN_DHCP6,WARP,WARP_IPV6
```

Check production state:

```sh
cat /var/db/gateway-ntfy-alert.state
```

Check test state:

```sh
cat /tmp/gateway-ntfy-alert.test.state
```

View logs:

```sh
grep 'gateway-ntfy-alert' /var/log/system/latest.log | tail -n 20
```

Syntax-check the script:

```sh
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Check permissions:

```sh
ls -l /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

## Disable Or Re-enable

Disable the syshook without deleting it:

```sh
chmod 644 /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Re-enable the syshook:

```sh
chmod 755 /usr/local/etc/rc.syshook.d/monitor/80-gateway-ntfy-alert
```

Manual test-mode runs still work while the syshook is executable. They use
`/tmp/gateway-ntfy-alert.test.state` and do not write production state.
