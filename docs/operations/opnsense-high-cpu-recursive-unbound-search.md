# OPNsense High CPU from Recursive Unbound Search

Date: 2026-07-18

Related current configuration inventory:
[OPNsense Current Non-Default Configuration](opnsense-current-non-default-config.md).

This document records a high-CPU incident caused by read-only diagnostic
commands and the guardrails required for future searches on OPNsense.

## Incident Summary

At `21:10 UTC`, OPNsense had load averages near `2.4` and sustained roughly
50% total CPU use on its four logical CPUs. Two `grep` processes each occupied
one full CPU core:

```text
PID 2650   grep -R ... taobao.com ... /var/unbound ...   about 100% CPU
PID 38842  grep -R ... chatgpt.com ... /var/unbound ... about 100% CPU
```

The commands had been started by non-interactive SSH sessions at `13:24 UTC`
and `13:20 UTC`, respectively. They were configuration-validation searches,
not OPNsense, Unbound, Zenarmor, AdGuardHome, WARP, or watchdog processes.

## Root Cause

`/var/unbound` is an Unbound chroot containing mounted subtrees. In particular:

```text
/var/unbound/dev -> mounted devfs
```

The recursive searches descended into that mount and opened:

```text
/var/unbound/dev/random
```

`procstat -f` showed file descriptor `3` on `dev/random` for both processes.
Unlike a finite regular file, this character device does not produce a normal
end-of-file for this use. Each `grep` therefore continued reading and matching
indefinitely.

The remote commands also assumed POSIX `sh` redirection while the OPNsense root
SSH login shell was `csh`. The resulting process arguments included a literal
`2`, reinforcing the rule that compound remote commands must select their
shell explicitly.

## Resolution and Verification

After confirming the process command lines and open files, both leaf `grep`
processes received `SIGTERM` at approximately `21:15 UTC`:

```sh
kill -TERM 2650 38842
```

Both processes exited. No OPNsense service was stopped, restarted, or
reconfigured. Subsequent samples showed:

```text
user:       0.6% to 0.8%
system:     1.0% to 1.6%
interrupt:  0.4%
idle:       97.4% to 97.8%
```

The one-, five-, and fifteen-minute load averages declined gradually, as
expected for time-decayed metrics.

## Mandatory Search Guardrails

Do not recursively search the whole Unbound chroot:

```sh
# Unsafe: can enter devfs and read an endless character device.
grep -R -n -E 'PATTERN' /var/unbound
```

Prefer known, explicit configuration files. When discovery under the chroot is
necessary, use FreeBSD `find -x` to stay on one filesystem, select only regular
files, and then invoke `grep`:

```sh
find -x /var/unbound -type f \
  -exec grep -n -I -E 'PATTERN' {} +
```

Both restrictions matter:

- `-x` prevents descent into mounted filesystems such as
  `/var/unbound/dev`.
- `-type f` prevents `grep` from receiving directories, sockets, pipes, or
  character devices.

Do not replace these safeguards with only `--exclude-dir=dev`; other mounted
subtrees may exist now or be added by a future OPNsense release or plugin.

For compound commands that need POSIX shell behavior, invoke `/bin/sh`
explicitly instead of relying on the root login shell. Keep commands narrowly
scoped and verify them before suppressing stderr.

## High-CPU Diagnostic Pattern

Use short, read-only samples first:

```sh
uptime
top -b -d 3 -s 2 -o cpu
ps axww -o pid,ppid,user,state,%cpu,%mem,time,command -r
```

If a diagnostic process is unexpectedly busy, inspect its open files before
terminating it or blaming the service named in its search pattern:

```sh
procstat -f <pid>
procstat -k <pid>
```

Character-device paths under a chroot, especially `dev/random` or `dev/zero`,
are a strong indication that a supposedly finite recursive search crossed a
mount boundary.
