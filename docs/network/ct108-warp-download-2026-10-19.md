# CT108 WARP routing — 2026-10-19

User explicitly authorized CT108 to use the existing router WARP interface.
Only 192.168.1.187 was added to the existing warp_hosts alias (UUID 7c0c6df1-cfd7-4c58-ae12-667aa8e40e98); no members were removed. Existing LAN and destination exceptions remain in force. CT108 has no active IPv6 address; no IPv6 policy was changed.

Configuration backup: `/conf/config.xml.pre-ct108-warp-20261019T101939Z` (0600).
Narrow change helper: `/root/configure-opnsense-ct108-warp.php`, maintained in the PVE project scripts directory.

After applying the helper, refresh the generated alias input before updating PF:

```sh
configctl template reload OPNsense/Filter
/usr/local/opnsense/scripts/filter/update_tables.py --aliases warp_hosts --output json
pfctl -t warp_hosts -T test 192.168.1.187
```

Calling update_tables alone initially did not apply the XML change because it consumes the generated filter_tables.conf. No full firewall restart was needed.

Verification: alias membership 1/1; CT108 Cloudflare trace warp=on and colo=DUB (previously warp=off). Download PF states show 192.168.1.187 translated to 172.16.0.2 through wg1. SSH, Samba and Zabbix Agent remain active. The existing wg1 MTU is 1280.

The same resumed 5.18 GiB Quark file with a locally patched 16-connection downloader measured about 8.20 MiB/s over 31 seconds after routing through WARP; direct routing previously measured about 4.11 MiB/s. These are observations at different times, not an isolated benchmark or guaranteed sustained rate. The completed download passed size and ffprobe checks.

To revert only this change:

```sh
php /root/configure-opnsense-ct108-warp.php --rollback
configctl template reload OPNsense/Filter
/usr/local/opnsense/scripts/filter/update_tables.py --aliases warp_hosts --output json
```

Restart only the affected download connections if necessary; existing states may retain their route. Do not restore the entire backup over unrelated later configuration changes.
