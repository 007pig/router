# OPNsense + Shelly Modem Watchdog

Date: 2026-06-30

Related network diagnostic:
[OPNsense IPv6 over DS-Lite with Connect Box](../network/ipv6-dslite-opnsense-connectbox.md).

Related current configuration inventory:
[OPNsense Current Non-Default Configuration](opnsense-current-non-default-config.md).

Related notification-only WAN link speed watchdog:
[OPNsense WAN Link Speed Watchdog](opnsense-wan-link-speed-watchdog.md).

Related notification-only gateway down/up alert:
[OPNsense Gateway ntfy Alert](opnsense-gateway-ntfy-alert.md).

This document records the modem watchdog installed on the OPNsense router. The goal is to reboot the cable modem automatically when the IPv4 WAN gateway stays down, while ignoring IPv6-only gateway changes.

## Current State

The watchdog is installed and enabled on OPNsense.

Verified again by read-only inspection on 2026-07-01: the script is executable,
`DRY_RUN` is still `false`, and the target gateway is still `WAN_DHCP`.

OPNsense router:

```sh
ssh root@192.168.1.1
```

Installed syshook script:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Current mode:

```php
const DRY_RUN = false;
```

This means the script is now live. If `WAN_DHCP` remains clearly down/offline after the debounce period, it will power-cycle the modem through Shelly.

Shelly Plug Plus UK:

```text
IP: 192.168.1.220
RPC endpoint: http://192.168.1.220/rpc/
```

The modem has been moved onto the Shelly plug and was verified from OPNsense before enabling live mode:

```json
"output": true
"apower": about 12 W
```

## What Was Changed

A new OPNsense Gateway Monitor syshook was installed:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

The script:

- Runs only when OPNsense Gateway Monitor fires a `monitor` syshook event.
- Checks the affected gateway name passed to the syshook.
- Only acts on `WAN_DHCP`.
- Ignores `WAN_DHCP6`, including up/down changes.
- Waits 90 seconds before making a decision.
- Rereads the current `WAN_DHCP` gateway status after the wait.
- Reboots the modem only if `WAN_DHCP` is still clearly `down` or `offline`.
- Does not reboot for packet-loss-only states by default.
- Uses a lock file to prevent concurrent reboot attempts.
- Uses a cooldown file to prevent repeated modem reboots.
- Logs decisions to the OPNsense system log with tag `modem-watchdog`.
- Uses Shelly local HTTP RPC with `toggle_after=20`, so power is restored by Shelly even if the script stops.

A logging improvement was made after initial testing: the script now writes logs via `/usr/bin/logger` first, with PHP `syslog()` as fallback. This made post-debounce decision logs appear reliably in OPNsense `System -> Log Files -> General`.

Backups made on OPNsense:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog.bak.20260630185013
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog.dryrun-on.bak.20260630213648
```

## Runtime Logic

Normal event flow:

```text
Gateway Monitor changes state
-> OPNsense runs monitor syshook scripts
-> 90-modem-watchdog receives affected gateway name
-> if gateway is not WAN_DHCP: log and exit
-> acquire lock
-> check cooldown
-> wait 90 seconds
-> reread current WAN_DHCP status
-> if status is not down/offline: log and exit
-> call Shelly Switch.Set with toggle_after=20
-> write cooldown timestamp
-> log result
```

Effective live action:

```text
WAN_DHCP down/offline for longer than 90 seconds
-> Shelly turns modem power off
-> Shelly automatically restores power after 20 seconds
-> watchdog will not trigger another reboot for 900 seconds
```

The Shelly action URL is:

```text
http://192.168.1.220/rpc/Switch.Set?id=0&on=false&toggle_after=20
```

## Key Parameters

These constants are near the top of the syshook script:

```php
const TARGET_GATEWAY = 'WAN_DHCP';
const SHELLY_IP = '192.168.1.220';
const SHELLY_SWITCH_ID = 0;

const DEBOUNCE_SECONDS = 90;
const SHELLY_OFF_SECONDS = 20;
const COOLDOWN_SECONDS = 900;

const DRY_RUN = false;
const REBOOT_ON_PACKET_LOSS = false;

const LOCK_FILE = '/var/run/modem-watchdog.lock';
const STATE_FILE = '/var/db/modem-watchdog.last-reboot';
```

Parameter meaning:

- `TARGET_GATEWAY`: only this gateway can trigger modem reboot logic.
- `SHELLY_IP`: fixed IP of the Shelly Plug Plus UK powering the modem.
- `SHELLY_SWITCH_ID`: Shelly relay ID, normally `0` for a single-plug device.
- `DEBOUNCE_SECONDS`: wait time after a gateway event before deciding.
- `SHELLY_OFF_SECONDS`: modem power-off duration before Shelly auto-restores power.
- `COOLDOWN_SECONDS`: minimum interval between real modem reboot attempts.
- `DRY_RUN`: when `true`, the script logs what it would do but does not call Shelly.
- `REBOOT_ON_PACKET_LOSS`: when `false`, loss/delay-only gateway states do not reboot the modem.
- `LOCK_FILE`: prevents multiple syshook events from running overlapping reboot flows.
- `STATE_FILE`: stores the last successful Shelly reboot timestamp for cooldown.

## Why WAN_DHCP6 Is Ignored

This network uses a cable modem with DS-Lite behavior. In this setup, IPv6 can remain online while IPv4 is broken.

Examples of failure modes where `WAN_DHCP6` may look healthy but IPv4 is still unusable:

- Native IPv6 path is working, but DS-Lite / AFTR / CGN IPv4 service is broken.
- The modem still forwards IPv6 traffic but its IPv4 path has failed.
- `WAN_DHCP6` monitor target responds, but `WAN_DHCP` monitor target is unreachable.

Therefore `WAN_DHCP6=Online` must not be used as proof that the modem or IPv4 WAN is healthy. The watchdog intentionally uses `WAN_DHCP` as the sole reboot decision gateway.

## Why Syshook Instead Of Cron

This watchdog uses OPNsense Gateway Monitor syshook events instead of a cron polling loop.

Advantages:

- Event-driven: it runs when gateway state changes instead of polling constantly.
- Uses OPNsense/dpinger gateway judgement rather than a separate ad hoc ping loop.
- Receives the affected gateway name, so it can ignore `WAN_DHCP6` precisely.
- Avoids duplicate network-health logic in Shelly or cron scripts.
- Reduces false positives by combining Gateway Monitor state, debounce, recheck, lock, and cooldown.

Shelly does not decide whether the network is broken. It only performs the power action when OPNsense tells it to.

## Useful Commands

Check watchdog setting:

```sh
grep '^const DRY_RUN' /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Syntax-check the script:

```sh
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Check file permissions:

```sh
ls -l /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Expected permissions:

```text
-rwxr-xr-x  root wheel
```

Check current OPNsense gateway status:

```sh
/usr/local/sbin/configctl interface gateways status
```

Check Shelly status:

```sh
curl -s "http://192.168.1.220/rpc/Switch.GetStatus?id=0"
```

Expected Shelly output while modem is powered:

```json
"output": true
```

The modem should also normally show non-zero power draw in `apower`.

View watchdog logs:

```sh
grep 'modem-watchdog' /var/log/system/latest.log | tail -n 20
```

OPNsense UI location:

```text
System -> Log Files -> General
```

Filter by:

```text
modem-watchdog
```

## Safe Tests

Test that IPv6 gateway events are ignored:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog WAN_DHCP6
```

Expected log:

```text
ignoring gateway event; affected=WAN_DHCP6 target=WAN_DHCP
```

Manual `WAN_DHCP` test:

```sh
/usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog WAN_DHCP
```

Important: now that `DRY_RUN=false`, this is no longer a purely harmless test. If `WAN_DHCP` is online, it should wait 90 seconds and exit without action. If `WAN_DHCP` is down/offline at the end of the 90-second debounce, it will actually power-cycle the modem.

Expected log when WAN is healthy:

```text
received WAN_DHCP monitor event; waiting 90 seconds before recheck
debounce complete; rereading current WAN_DHCP status
WAN_DHCP recovered or is not a reboot condition after debounce; status=none translated=Online ... source=configctl
```

## Disable Or Re-enable

Temporarily switch back to dry-run mode:

```sh
sed -i '' 's/^const DRY_RUN = false;/const DRY_RUN = true;/' /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Switch from dry-run back to live mode:

```sh
sed -i '' 's/^const DRY_RUN = true;/const DRY_RUN = false;/' /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Disable the syshook without deleting it:

```sh
chmod 644 /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Re-enable the syshook:

```sh
chmod 755 /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Restore the last dry-run backup:

```sh
cp -p /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog.dryrun-on.bak.20260630213648 /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
chmod 755 /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
/usr/local/bin/php -l /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Clear cooldown manually only when you intentionally want to allow another reboot attempt immediately:

```sh
rm -f /var/db/modem-watchdog.last-reboot
```

## Emergency Operations

Turn Shelly output on manually:

```sh
curl -s "http://192.168.1.220/rpc/Switch.Set?id=0&on=true"
```

Turn Shelly output off and auto-restore after 20 seconds:

```sh
curl -s "http://192.168.1.220/rpc/Switch.Set?id=0&on=false&toggle_after=20"
```

Use the second command only when a brief modem outage is acceptable.

If the watchdog appears to be acting unexpectedly, first disable execution:

```sh
chmod 644 /usr/local/etc/rc.syshook.d/monitor/90-modem-watchdog
```

Then inspect logs:

```sh
grep 'modem-watchdog' /var/log/system/latest.log | tail -n 50
/usr/local/sbin/configctl interface gateways status
curl -s "http://192.168.1.220/rpc/Switch.GetStatus?id=0"
```

## Installed Script Snapshot

This is the installed script content as of 2026-06-30 after live mode was enabled.

```php
#!/usr/local/bin/php
<?php

/*
 * OPNsense Gateway Monitor syshook modem watchdog.
 *
 * Triggers only for TARGET_GATEWAY events. After a debounce delay it rereads
 * the current gateway status and only power-cycles the modem if the IPv4 WAN
 * gateway is still clearly down/offline.
 */

const LOG_TAG = 'modem-watchdog';

const TARGET_GATEWAY = 'WAN_DHCP';
const SHELLY_IP = '192.168.1.220';
const SHELLY_SWITCH_ID = 0;

const DEBOUNCE_SECONDS = 90;
const SHELLY_OFF_SECONDS = 20;
const COOLDOWN_SECONDS = 900;

/*
 * Keep this true for first install/testing. Set to false only after logs show
 * the expected decisions.
 */
const DRY_RUN = false;

/*
 * Default is intentionally conservative. When false, packet-loss-only states
 * such as "loss" do not reboot the modem. Set true only if you explicitly want
 * persistent packet-loss states to power-cycle the modem after debounce.
 */
const REBOOT_ON_PACKET_LOSS = false;

const LOCK_FILE = '/var/run/modem-watchdog.lock';
const STATE_FILE = '/var/db/modem-watchdog.last-reboot';

openlog(LOG_TAG, LOG_PID | LOG_NDELAY, LOG_DAEMON);

function syslog_priority(int $level): string
{
    return match ($level) {
        LOG_ERR => 'daemon.err',
        LOG_WARNING => 'daemon.warning',
        LOG_NOTICE => 'daemon.notice',
        default => 'daemon.info',
    };
}

function mw_log(string $message, int $level = LOG_NOTICE): void
{
    if (function_exists('exec') && is_executable('/usr/bin/logger')) {
        $cmd = '/usr/bin/logger -t ' . escapeshellarg(LOG_TAG) .
            ' -p ' . escapeshellarg(syslog_priority($level)) .
            ' ' . escapeshellarg($message) . ' 2>/dev/null';
        @exec($cmd);
        return;
    }

    syslog($level, $message);
}

function affected_gateways(array $argv): array
{
    if (empty($argv[1])) {
        return [];
    }

    $items = explode(',', $argv[1]);
    $items = array_map('trim', $items);
    return array_values(array_filter($items, static fn($v) => $v !== ''));
}

function acquire_lock()
{
    $fh = @fopen(LOCK_FILE, 'c');
    if ($fh === false) {
        mw_log('cannot open lock file ' . LOCK_FILE . '; conservative exit', LOG_WARNING);
        return false;
    }

    if (!flock($fh, LOCK_EX | LOCK_NB)) {
        mw_log('another watchdog instance is already running; exiting');
        fclose($fh);
        return false;
    }

    return $fh;
}

function cooldown_remaining(): int
{
    if (!is_readable(STATE_FILE)) {
        return 0;
    }

    $last = (int)trim((string)@file_get_contents(STATE_FILE));
    if ($last <= 0) {
        return 0;
    }

    $remaining = COOLDOWN_SECONDS - (time() - $last);
    return max(0, $remaining);
}

function mark_reboot_attempt(): void
{
    @file_put_contents(STATE_FILE, (string)time() . PHP_EOL, LOCK_EX);
}

function normalize_gateways(array $raw): array
{
    $result = [];

    foreach ($raw as $key => $entry) {
        if (!is_array($entry)) {
            continue;
        }

        $name = (string)($entry['name'] ?? $key);
        if ($name === '') {
            continue;
        }

        $result[$name] = $entry;
    }

    return $result;
}

function gateways_from_php(): array
{
    try {
        require_once 'config.inc';
        require_once 'legacy_bindings.inc';

        if (!function_exists('return_gateways_status')) {
            return [];
        }

        $raw = return_gateways_status();
        if (!is_array($raw)) {
            return [];
        }

        return normalize_gateways($raw);
    } catch (Throwable $e) {
        mw_log('return_gateways_status failed: ' . $e->getMessage(), LOG_WARNING);
        return [];
    }
}

function gateways_from_configctl(): array
{
    if (!function_exists('shell_exec')) {
        mw_log('shell_exec unavailable; cannot use configctl fallback', LOG_WARNING);
        return [];
    }

    $json = @shell_exec('/usr/local/sbin/configctl interface gateways status 2>/dev/null');
    if (!is_string($json) || trim($json) === '') {
        return [];
    }

    $raw = json_decode($json, true);
    if (!is_array($raw)) {
        mw_log('configctl gateway status returned invalid JSON; conservative exit', LOG_WARNING);
        return [];
    }

    return normalize_gateways($raw);
}

function read_gateway(string $name): ?array
{
    $gateways = gateways_from_php();
    if (isset($gateways[$name])) {
        return ['source' => 'return_gateways_status', 'data' => $gateways[$name]];
    }

    $gateways = gateways_from_configctl();
    if (isset($gateways[$name])) {
        return ['source' => 'configctl', 'data' => $gateways[$name]];
    }

    return null;
}

function status_text(array $gateway): string
{
    return strtolower(trim((string)($gateway['status'] ?? '')));
}

function gateway_is_reboot_condition(array $gateway): bool
{
    $status = status_text($gateway);

    if ($status === 'down' || $status === 'offline') {
        return true;
    }

    if (REBOOT_ON_PACKET_LOSS && ($status === 'loss' || $status === 'highloss' || $status === 'packetloss')) {
        return true;
    }

    return false;
}

function shelly_url(): string
{
    return sprintf(
        'http://%s/rpc/Switch.Set?id=%d&on=false&toggle_after=%d',
        SHELLY_IP,
        SHELLY_SWITCH_ID,
        SHELLY_OFF_SECONDS
    );
}

function http_get(string $url): array
{
    if (is_executable('/usr/local/bin/curl')) {
        $cmd = '/usr/local/bin/curl -sS --connect-timeout 3 --max-time 8 --fail ' . escapeshellarg($url) . ' 2>&1';
        $lines = [];
        $rc = 0;
        exec($cmd, $lines, $rc);
        return [$rc === 0, implode("\n", $lines)];
    }

    $ctx = stream_context_create(['http' => ['timeout' => 8]]);
    $body = @file_get_contents($url, false, $ctx);
    return [$body !== false, $body === false ? '' : $body];
}

$affected = affected_gateways($argv);

if (!in_array(TARGET_GATEWAY, $affected, true)) {
    mw_log('ignoring gateway event; affected=' . implode(',', $affected) . ' target=' . TARGET_GATEWAY);
    exit(0);
}

$lock = acquire_lock();
if ($lock === false) {
    exit(0);
}

$remaining = cooldown_remaining();
if ($remaining > 0) {
    mw_log('cooldown active; skipping reboot for ' . $remaining . ' more seconds');
    exit(0);
}

mw_log('received ' . TARGET_GATEWAY . ' monitor event; waiting ' . DEBOUNCE_SECONDS . ' seconds before recheck');

sleep(DEBOUNCE_SECONDS);

mw_log('debounce complete; rereading current ' . TARGET_GATEWAY . ' status');

$remaining = cooldown_remaining();
if ($remaining > 0) {
    mw_log('cooldown became active during debounce; skipping reboot for ' . $remaining . ' more seconds');
    exit(0);
}

$read = read_gateway(TARGET_GATEWAY);
if ($read === null) {
    mw_log('cannot read current status for ' . TARGET_GATEWAY . '; conservative exit without reboot', LOG_WARNING);
    exit(0);
}

$gateway = $read['data'];
$status = status_text($gateway);
$translated = (string)($gateway['status_translated'] ?? '');
$loss = (string)($gateway['loss'] ?? '');
$delay = (string)($gateway['delay'] ?? '');

if (!gateway_is_reboot_condition($gateway)) {
    mw_log(
        TARGET_GATEWAY . ' recovered or is not a reboot condition after debounce; ' .
        'status=' . $status .
        ' translated=' . $translated .
        ' loss=' . $loss .
        ' delay=' . $delay .
        ' source=' . $read['source']
    );
    exit(0);
}

$url = shelly_url();

if (DRY_RUN) {
    mw_log(
        'dry-run: would power-cycle modem via Shelly; ' .
        'gateway=' . TARGET_GATEWAY .
        ' status=' . $status .
        ' source=' . $read['source'] .
        ' url=' . $url
    );
    exit(0);
}

mw_log(
    'power-cycling modem via Shelly; ' .
    'gateway=' . TARGET_GATEWAY .
    ' status=' . $status .
    ' off_seconds=' . SHELLY_OFF_SECONDS .
    ' cooldown=' . COOLDOWN_SECONDS
);

[$ok, $body] = http_get($url);
$body = trim($body);

if ($ok) {
    mark_reboot_attempt();
    mw_log('Shelly RPC succeeded; response=' . substr($body, 0, 300));
    exit(0);
}

mw_log('Shelly RPC failed; response=' . substr($body, 0, 300), LOG_ERR);
exit(1);
```
