<?php

use function ModemWatchdog\{acquireLock, gatewayStatus, loadState, probeResult, runPoll};

require $argv[1] ?? dirname(__DIR__) . '/modem-watchdog';

function expect(mixed $actual, mixed $expected, string $message): void
{
    if ($actual !== $expected) {
        throw new RuntimeException($message . ': ' . var_export($actual, true));
    }
}

$directory = sys_get_temp_dir() . '/modem-watchdog-test-' . bin2hex(random_bytes(8));
if (!mkdir($directory, 0700)) {
    throw new RuntimeException('cannot create test directory');
}

try {
    $path = $directory . '/state.json';
    $ready = ['id' => 0, 'output' => true];
    $switch = $ready;
    $attempts = [];
    $log = [];
    $now = 10000;
    $accepted = false;
    $poll = static function (string $sample, int $time, int $boot = 1, bool $dryRun = false)
        use ($path, &$now, &$switch, &$attempts, &$log, &$accepted): void {
        $now = $time;
        runPoll(
            $path,
            $boot,
            $sample,
            $dryRun,
            static function () use (&$switch): ?array { return $switch; },
            static function () use ($path, &$now, &$attempts, &$accepted): bool {
                $state = loadState($path);
                expect($state['last_attempt_at'], $now, 'attempt is reserved before RPC');
                $attempts[] = $now;
                return $accepted;
            },
            static function () use (&$now): int { return $now; },
            static function (string $message) use (&$log): void { $log[] = $message; }
        );
    };

    $wan = ['name' => 'WAN_DHCP', 'loss' => '100.0 %'];
    expect(gatewayStatus($wan + ['status' => 'down']), 'down', 'IPv4 down qualifies');
    expect(gatewayStatus($wan + ['status' => 'force_down']), 'other', 'manual force-down is excluded');
    expect(gatewayStatus($wan + ['status' => 'loss']), 'other', 'loss-only is excluded');
    expect(gatewayStatus($wan + ['status' => 'delay']), 'other', 'delay-only is excluded');
    expect(gatewayStatus(['name' => 'WAN_DHCP6', 'status' => 'down', 'loss' => '100.0 %']), 'unknown', 'IPv6 ignored');
    expect(gatewayStatus(['name' => 'WAN_DHCP', 'status' => 'down', 'loss' => '~']), 'unknown', 'monitor not initialized');
    expect(gatewayStatus(null), 'unknown', 'missing gateway');
    expect(probeResult(0, ''), 'reachable', 'at least one direct WAN reply');
    expect(probeResult(2, '3 packets transmitted, 0 packets received, 100.0% packet loss'), 'unreachable', 'loss confirmed');
    expect(probeResult(2, '1 packets transmitted, 0 packets received, 100.0% packet loss'), 'unknown', 'incomplete probe');
    expect(probeResult(1, ''), 'unknown', 'probe execution error');

    // The IPv4 gateway is down independently of alarm dispatch, IPv6, WARP, and DNS.
    $poll('down', 10000);
    $poll('down', 10060);
    expect($attempts, [], 'two samples do not qualify');
    $poll('down', 10120);
    expect($attempts, [10120], 'first attempt on third sample');
    expect(str_contains(end($log), 'shelly_outcome=unconfirmed'), true, 'ambiguous RPC consumes an attempt');
    for ($time = 10180; $time < 11020; $time += 60) {
        $poll('down', $time);
    }
    expect($attempts, [10120], 'cooldown excludes second attempt before 15 minutes');
    $accepted = true;
    $poll('down', 11020);
    expect($attempts, [10120, 11020], 'second attempt at 15 minutes');
    expect(str_contains(end($log), 'shelly_outcome=accepted'), true, 'accepted RPC recorded');
    $poll('down', 11920, 2);
    $poll('down', 11980, 2);
    $poll('down', 12040, 2);
    expect($attempts, [10120, 11020], 'two-attempt limit survives reboot');
    $poll('online', 12100, 2);
    expect(loadState($path)['attempts'], 2, 'single online sample cannot rearm');
    $poll('online', 12160, 2);
    expect(loadState($path)['attempts'], 0, 'two online checks rearm');
    $poll('down', 12220, 2);
    $poll('other', 12280, 2);
    $poll('down', 12340, 2);
    $poll('unknown', 12400, 2);
    $poll('down', 12460, 2);
    $poll('down', 12520, 2);
    $poll('down', 12640, 2);
    $poll('down', 12700, 3);
    $poll('down', 12760, 3);
    expect($attempts, [10120, 11020], 'replies, errors, missed runs, and restarts interrupt the count');

    $switch = null;
    $poll('down', 12820, 3);
    expect(str_contains(end($log), 'shelly=unavailable'), true, 'read failure defers');
    $switch = ['id' => 0, 'output' => false];
    $poll('down', 12880, 3);
    expect(str_contains(end($log), 'shelly=off'), true, 'manual off defers');
    $switch = $ready + ['timer_started_at' => 12900, 'timer_duration' => 180];
    $poll('down', 12940, 3);
    expect(str_contains(end($log), 'shelly=timer-active'), true, 'running timer defers');
    expect(loadState($path)['attempts'], 0, 'preflight failures do not consume attempts');
    $switch = $ready;
    $poll('down', 13000, 3, true);
    expect($attempts, [10120, 11020], 'dry run never calls the power RPC');
    expect(str_contains(end($log), 'would-power-cycle'), true, 'dry run covers full decision');
    $poll('online', 13060, 3);
    $poll('online', 13120, 3);
    $poll('down', 13180, 3);
    $poll('down', 13240, 3);
    $poll('down', 13300, 3);
    expect(str_contains(end($log), 'action=cooldown'), true, 'cooldown survives short recovery');

    $lock = acquireLock($directory . '/lock');
    expect(acquireLock($directory . '/lock'), null, 'parallel run blocked');
    fclose($lock);
    $lock = acquireLock($directory . '/lock');
    expect(is_resource($lock), true, 'lock is reusable');
    fclose($lock);

    $writeFailure = $directory . '/failure';
    mkdir($writeFailure, 0700);
    $failureState = $writeFailure . '/state.json';
    foreach ([20000, 20060] as $time) {
        runPoll($failureState, 1, 'down', false, static fn () => $ready,
            static fn () => throw new LogicException('unexpected RPC'), static fn () => $time, static fn () => null);
    }
    try {
        runPoll($failureState, 1, 'down', false,
            static function () use ($ready, $failureState): array {
                unlink($failureState);
                mkdir($failureState);
                return $ready;
            },
            static fn () => throw new LogicException('RPC sent despite failed state write'),
            static fn () => 20120, static fn () => null);
        throw new LogicException('failed state write was ignored');
    } catch (RuntimeException $error) {
        expect($error->getMessage(), 'cannot publish watchdog state', 'state write failure is fail-closed');
    }
    rmdir($failureState);
    rmdir($writeFailure);

    file_put_contents($path, '{');
    try {
        $poll('down', 13400, 3);
        throw new LogicException('corrupt state was ignored');
    } catch (RuntimeException $error) {
        expect($error->getMessage(), 'invalid watchdog state', 'state corruption is fail-closed');
    }
    fwrite(STDOUT, "modem watchdog scenarios passed\n");
} finally {
    foreach (glob($directory . '/*') as $file) {
        if (is_file($file)) {
            unlink($file);
        }
    }
    rmdir($directory);
}
