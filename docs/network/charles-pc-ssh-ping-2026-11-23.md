# Charles-PC SSH and ping timeout

On 2026-11-23, the OPNsense Dnsmasq lease identified `192.168.1.29` as
`Charles-PC`. The Mac at `192.168.1.115/24` reached that address directly at
layer 2 over `bridge1`. OPNsense also had a directly connected route over its
LAN interface `igc1`.

| Test to `192.168.1.29` | Mac `192.168.1.115` | OPNsense `192.168.1.1` |
| --- | --- | --- |
| TCP `11434` | Connected | Connected |
| TCP `22` | Timed out | Timed out |
| ICMP echo | 0 of 2 replies | 0 of 2 replies |

A bounded packet capture on `igc1` showed the TCP handshake for `11434`,
outgoing SYNs for `22` with no SYN-ACK or reset, and outgoing ICMP echo
requests with no echo replies. PF created state for the port `22` probe and
recorded it as `SYN_SENT:CLOSED`.

These observations rule out OPNsense PF blocking the tested connections. The
Windows-side listener and inbound firewall profile still need to be checked
to identify the cause of the port `22` timeout.

Related [OPNsense firewall policy](../operations/opnsense-current-non-default-config.md#firewall-policy).
