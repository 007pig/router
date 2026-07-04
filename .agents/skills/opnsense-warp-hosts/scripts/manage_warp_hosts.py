#!/usr/bin/env python3
import argparse
import datetime as dt
import ipaddress
import json
import re
import subprocess
import sys


DEFAULT_ROUTER = "root@192.168.1.1"
DEFAULT_ALIAS = "warp_hosts"
DEFAULT_INTERFACE = "en0"


def run(cmd, *, input_text=None, check=True):
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "command failed: {}\nexit={}\nstdout={}\nstderr={}".format(
                " ".join(cmd), proc.returncode, proc.stdout.strip(), proc.stderr.strip()
            )
        )
    return proc


def ssh_cmd(router, remote_command, *, check=True):
    return run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            router,
            remote_command,
        ],
        check=check,
    )


def ssh_php(router, php_code, *, check=True):
    return run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            router,
            "php",
        ],
        input_text=php_code,
        check=check,
    )


def canonical_ip(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("{} is not an IPv4/IPv6 host address".format(value)) from exc


def alias_name(value):
    if re.fullmatch(r"[A-Za-z0-9_]+", value) is None:
        raise argparse.ArgumentTypeError("{} is not a safe OPNsense alias name".format(value))
    return value


def discover_local_macos_addresses(interface):
    proc = run(["ifconfig", interface])
    addresses = []
    for line in proc.stdout.splitlines():
        inet_match = re.match(r"\s+inet\s+([0-9.]+)\s+", line)
        if inet_match:
            addresses.append(canonical_ip(inet_match.group(1)))
            continue

        inet6_match = re.match(r"\s+inet6\s+([0-9a-fA-F:]+)(?:%[^\s]+)?\s+", line)
        if inet6_match:
            value = canonical_ip(inet6_match.group(1))
            if value.lower().startswith("fe80:"):
                continue
            addresses.append(value)

    return dedupe(addresses)


def dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_php(payload):
    payload_json = json.dumps(payload, separators=(",", ":"))
    return """<?php
require_once("config.inc");
require_once("util.inc");

global $config;

$payload = json_decode(<<<'JSON'
%s
JSON
, true);

if (!is_array($payload)) {
    fwrite(STDERR, "invalid payload\\n");
    exit(1);
}

$alias_name = $payload["alias"];
$action = $payload["action"];
$addresses = $payload["addresses"];

if (
    isset($config["OPNsense"]["Firewall"]["Alias"]["aliases"]["alias"]) === false ||
    is_array($config["OPNsense"]["Firewall"]["Alias"]["aliases"]["alias"]) === false
) {
    fwrite(STDERR, "alias config path not found\\n");
    exit(1);
}

$aliases =& $config["OPNsense"]["Firewall"]["Alias"]["aliases"]["alias"];
$found = false;
$changed = false;
$before = array();
$after = array();
$added = array();
$removed = array();

foreach ($aliases as &$alias) {
    if (($alias["name"] ?? "") !== $alias_name) {
        continue;
    }

    $found = true;
    $lines = preg_split("/\\r?\\n/", $alias["content"] ?? "");
    foreach ($lines as $line) {
        $entry = trim($line);
        if ($entry !== "") {
            $before[] = $entry;
        }
    }

    $after = $before;

    if ($action === "add") {
        foreach ($addresses as $entry) {
            if (in_array($entry, $after, true) === false) {
                $after[] = $entry;
                $added[] = $entry;
                $changed = true;
            }
        }
    } elseif ($action === "remove") {
        $new_after = array();
        foreach ($after as $entry) {
            if (in_array($entry, $addresses, true)) {
                $removed[] = $entry;
                $changed = true;
                continue;
            }
            $new_after[] = $entry;
        }
        $after = $new_after;
    } elseif ($action === "list") {
        $changed = false;
    } else {
        fwrite(STDERR, "unsupported action\\n");
        exit(1);
    }

    if ($changed) {
        $alias["content"] = implode("\\n", $after);
    }
}
unset($alias);

if ($found === false) {
    fwrite(STDERR, "alias not found: " . $alias_name . "\\n");
    exit(1);
}

if ($changed) {
    write_config("Update " . $alias_name . " via manage_warp_hosts.py");
}

echo json_encode(array(
    "alias" => $alias_name,
    "action" => $action,
    "changed" => $changed,
    "added" => $added,
    "removed" => $removed,
    "before" => $before,
    "after" => $after,
), JSON_PRETTY_PRINT) . "\\n";
""" % payload_json


def read_alias(router, alias_name):
    payload = {"action": "list", "alias": alias_name, "addresses": []}
    proc = ssh_php(router, build_php(payload))
    return json.loads(proc.stdout)


def print_entries(title, entries):
    print(title)
    for entry in entries:
        print("  {}".format(entry))


def make_backup(router):
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = "/conf/config.xml.pre-warp-hosts-{}".format(timestamp)
    ssh_cmd(router, "cp -p /conf/config.xml {}".format(path))
    return path


def validate_and_reload(router, alias_name):
    ssh_cmd(router, "xmllint --noout /conf/config.xml")
    ssh_cmd(router, "configctl filter reload")
    ssh_cmd(router, "configctl filter refresh_aliases")
    proc = ssh_cmd(router, "pfctl -t {} -T show".format(alias_name))
    return proc.stdout


def parse_args():
    parser = argparse.ArgumentParser(description="Manage OPNsense warp_hosts alias entries.")
    parser.add_argument("action", choices=["list", "add", "remove"])
    parser.add_argument("--router", default=DEFAULT_ROUTER)
    parser.add_argument("--alias", default=DEFAULT_ALIAS, type=alias_name)
    parser.add_argument("--address", action="append", type=canonical_ip, default=[])
    parser.add_argument("--from-local-macos", action="store_true")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    addresses = list(args.address)
    if args.from_local_macos:
        addresses.extend(discover_local_macos_addresses(args.interface))
    addresses = dedupe(addresses)

    if args.action in {"add", "remove"} and not addresses:
        print("add/remove requires --address or --from-local-macos", file=sys.stderr)
        return 2

    if args.action == "list":
        result = read_alias(args.router, args.alias)
        print_entries("{} entries:".format(args.alias), result["after"])
        return 0

    current = read_alias(args.router, args.alias)
    current_entries = current["after"]

    if args.action == "add":
        would_change = [entry for entry in addresses if entry not in current_entries]
    else:
        would_change = [entry for entry in addresses if entry in current_entries]

    print_entries("target addresses:", addresses)

    if not would_change:
        print("No changes needed.")
        print_entries("{} entries:".format(args.alias), current_entries)
        return 0

    print_entries("entries to {}:".format(args.action), would_change)

    if args.dry_run:
        print("Dry run: no backup, write, validation, or reload performed.")
        return 0

    backup_path = make_backup(args.router)
    print("backup: {}".format(backup_path))

    payload = {"action": args.action, "alias": args.alias, "addresses": addresses}
    proc = ssh_php(args.router, build_php(payload))
    result = json.loads(proc.stdout)

    if result["changed"]:
        print_entries("added:", result["added"])
        print_entries("removed:", result["removed"])
        loaded_table = validate_and_reload(args.router, args.alias)
        print("filter reload: OK")
        print("{} loaded PF table:".format(args.alias))
        print(loaded_table.rstrip())
    else:
        print("No changes were written after re-reading remote config.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
