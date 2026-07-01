# Wi-Fi AP And Mesh Topology

Date observed: 2026-07-01

This document records the current OpenWrt AP layout and mesh relationships on
the `192.168.1.0/24` LAN. It is based on read-only SSH inspection of the APs
and OPNsense. No AP, router, wireless, firewall, DHCP, or mesh settings were
changed during this inspection.

Sensitive values are intentionally omitted. This includes passwords, SAE/PSK
keys, MAC addresses, client hardware identifiers, and other credentials.

## Inspection Sources

Read-only sources used on 2026-07-01:

```sh
ssh root@192.168.1.1
ssh root@192.168.1.253
ssh root@192.168.1.254
ssh root@192.168.1.101
ssh root@192.168.1.102
ssh root@192.168.1.105
```

`192.168.1.252` did not accept SSH during the inspection.

Commands used included:

```sh
uci show network
uci show wireless
uci show dhcp
ip -br addr
ip route
bridge link
brctl show
iw dev
iwinfo
batctl if
batctl n
batctl o
arp -an
ping
```

AP system clocks were not all reliable during inspection, so the observation
date above is from the workstation/session date rather than the AP clocks.

Local DHCP service on the reachable OpenWrt APs was configured with LAN DHCP
ignored (`dhcp.lan.ignore=1`). The LAN DHCP authority for AP management
addresses is OPNsense.

## Inventory

| IP | Hostname | Model | Addressing | Mesh role |
| --- | --- | --- | --- | --- |
| `192.168.1.252` | `EAX12-2ndfloor` | Netgear EAX12 | OPNsense DHCP reservation; AP unreachable by SSH/ICMP at observation time | Seen indirectly as the 2.4 GHz mesh peer of `ng-2ndfloor` |
| `192.168.1.253` | `EAX12-kitchen` | Netgear EAX12 | Static IP on AP, gateway/DNS `192.168.1.1` | 5 GHz batman-adv mesh node |
| `192.168.1.254` | `EAX12-hall` | Netgear EAX12 | Static IP on AP, gateway/DNS `192.168.1.1` | 5 GHz batman-adv mesh node |
| `192.168.1.101` | `ng-groundfloor` | Netgear WAX214v2 | DHCP from OPNsense reservation | 5 GHz batman-adv mesh node |
| `192.168.1.102` | `ng-2ndfloor` | Netgear WAX214v2 | DHCP from OPNsense reservation | 2.4 GHz batman-adv mesh node linked to `EAX12-2ndfloor` |
| `192.168.1.105` | `ng-1stfloor` | Netgear WAX214v2 | DHCP from OPNsense reservation | No active mesh/batman role observed |

All reachable APs are OpenWrt SNAPSHOT builds on `ramips/mt7621` with Linux
`6.12.60`.

Observed builds:

```text
EAX12-kitchen:   OpenWrt SNAPSHOT r32228-a90fb76736
EAX12-hall:      OpenWrt SNAPSHOT r32228-a90fb76736
ng-groundfloor:  OpenWrt SNAPSHOT r32307-24b8db118b
ng-2ndfloor:     OpenWrt SNAPSHOT r32307-24b8db118b
ng-1stfloor:     OpenWrt SNAPSHOT r32307-24b8db118b
```

## High-Level Layout

```text
OPNsense LAN, 192.168.1.1/24
|
|-- myhome2 APs on all reachable APs
|-- extra SSIDs on selected APs
|   |-- myhome-iot on EAX12-kitchen
|   `-- myhome-wallbox on EAX12-hall and ng-groundfloor
|
|-- batman-adv mesh segment A, 5 GHz channel 48 HE40
|   |-- EAX12-kitchen   192.168.1.253
|   |-- EAX12-hall      192.168.1.254
|   `-- ng-groundfloor  192.168.1.101
|
`-- batman-adv mesh segment B, 2.4 GHz channel 6 HE20
    |-- ng-2ndfloor     192.168.1.102
    `-- EAX12-2ndfloor  192.168.1.252, management IP unreachable
```

Both mesh segments use the configured mesh ID:

```text
myhome-mesh-bat
```

Using the same mesh ID does not make the two observed RF segments the same
wireless cell. Segment A is on 5 GHz channel 48; segment B is on 2.4 GHz
channel 6. A device must have an active mesh interface on the same band/channel
to be a direct RF peer.

The mesh wireless interfaces are attached to a `batadv_hardif` interface named
`batmesh`, which joins `bat0`. On mesh-capable APs, `bat0` is bridged into
`br-lan` alongside the local LAN port and AP wireless interfaces.

## Mesh Segment A: 253, 254, 101

The active 5 GHz mesh uses:

```text
radio: 5 GHz
channel: 48
width: HE40
mesh ID: myhome-mesh-bat
mesh encryption configured in UCI: SAE
batman-adv algorithm: BATMAN_IV
bat0 gateway mode: off
bridge loop avoidance: enabled
hop penalty: 30
```

Observed active peers:

```text
EAX12-kitchen  <-> EAX12-hall
EAX12-kitchen  <-> ng-groundfloor
EAX12-hall     <-> ng-groundfloor
```

The three nodes form a full mesh at the 802.11s/batman layer. `batctl n` and
`batctl o` on each reachable node showed the other two nodes as active
neighbors/originators with recent last-seen values.

Although `EAX12-2ndfloor` (`192.168.1.252`) is expected to participate in the
mesh, it was not listed as a neighbor or originator by `EAX12-kitchen`,
`EAX12-hall`, or `ng-groundfloor` on this 5 GHz segment during the inspection.

Approximate mesh link state at observation time:

| Local node | Peer node | Link state | Observed quality |
| --- | --- | --- | --- |
| `EAX12-kitchen` | `EAX12-hall` | Established | medium signal, direct path |
| `EAX12-kitchen` | `ng-groundfloor` | Established | strong signal, direct path |
| `EAX12-hall` | `ng-groundfloor` | Established | weaker signal than the kitchen link, direct path |

The `myhome2` SSID is broadcast on both 2.4 GHz and 5 GHz on these three APs.
Fast transition and neighbor assistance options are configured for `myhome2`
interfaces, including 802.11r and 802.11k/v-style settings. PSKs are omitted
from this document.

Additional SSIDs on this segment:

```text
EAX12-kitchen: myhome-iot on 2.4 GHz
EAX12-hall:    myhome-wallbox on 2.4 GHz
ng-groundfloor: myhome-wallbox on 2.4 GHz
```

## Mesh Segment B: 102 And 252

`ng-2ndfloor` has a separate active 2.4 GHz mesh interface:

```text
radio: 2.4 GHz
channel: 6
width: HE20
mesh ID: myhome-mesh-bat
mesh encryption configured in UCI: SAE
batman-adv algorithm: BATMAN_IV
bridge: bat0 is bridged into br-lan
```

Observed peer:

```text
ng-2ndfloor <-> EAX12-2ndfloor
```

The peer was mapped to `EAX12-2ndfloor` by comparing the mesh peer seen from
`ng-2ndfloor` with the OPNsense DHCP static reservation for
`192.168.1.252`. The hardware identifiers are intentionally omitted here.

At observation time the `ng-2ndfloor` side reported:

```text
mesh plink: ESTAB
mesh airtime link metric: 31
signal: about -36 dBm
expected throughput: about 232 Mbps
batman originator: direct, best path via the only mesh peer
```

This indicates that the wireless mesh link between `ng-2ndfloor` and
`EAX12-2ndfloor` was up even though the `192.168.1.252` management address was
not reachable.

`ng-2ndfloor` has the `myhome2` SSID active on 5 GHz channel 100 HE80. Its
2.4 GHz `myhome2` AP interface is configured but disabled. Its active mesh is
on 2.4 GHz.

## Non-Mesh AP: 105

`ng-1stfloor` is a normal bridged AP in the current snapshot.

Observed state:

```text
br-lan ports: LAN port, 2.4 GHz myhome2 AP, 5 GHz myhome2 AP
batctl: missing
active mesh interface: none observed
```

It broadcasts `myhome2` on:

```text
2.4 GHz: channel auto, runtime channel 6, HE20
5 GHz: channel 52, HE80
```

MAC deny lists are configured on some `myhome2` interfaces. The denied client
identifiers are omitted from this document.

## 252 Failure State

`192.168.1.252` was not reachable as a management IP during the 2026-07-01
inspection.

Observed symptoms:

```text
ssh root@192.168.1.252: connection timed out
ping from workstation to 192.168.1.252: 100% packet loss
ping from OPNsense to 192.168.1.252: 100% packet loss
OPNsense ARP table: no entry for 192.168.1.252
OPNsense ARP table: entries present for 101, 102, 105, 253, and 254
```

One workstation ping test received ICMP redirect/host-unreachable responses
from `EAX12-hall` (`192.168.1.254`) while targeting `192.168.1.252`. That
suggests local path confusion or stale routing/neighbor behavior around the
unreachable host, but it does not by itself prove that `EAX12-hall` is the
cause.

Important distinction:

- The `EAX12-2ndfloor` wireless mesh radio appears to be associated with
  `ng-2ndfloor`.
- The `192.168.1.252` management address does not respond and is not visible
  in the OPNsense ARP table.

The current evidence points to a management-plane or bridge/IP reachability
problem on `EAX12-2ndfloor`, not a simple absence of the 2.4 GHz mesh radio.
Do not reboot, reset, or power-cycle APs as part of investigation unless an
operator explicitly authorizes an outage-risking change.

## Suggested Read-Only Follow-Up

These checks are read-only and are useful before making any configuration
change:

1. From OPNsense, verify whether `192.168.1.252` appears after clearing only
   stale local observation state by waiting and re-running:

   ```sh
   arp -an | grep 192.168.1.252
   ping -c 3 192.168.1.252
   ```

2. From `ng-2ndfloor`, inspect whether `EAX12-2ndfloor` advertises any clients
   over batman-adv:

   ```sh
   batctl n
   batctl o
   batctl tg
   iw dev phy0-mesh0 station dump
   iw dev phy0-mesh0 mpath dump
   ```

3. From `ng-2ndfloor`, check whether bridge learning shows traffic behind the
   mesh peer:

   ```sh
   brctl showmacs br-lan
   bridge fdb show br br-lan
   ```

4. If physical access is available, inspect `EAX12-2ndfloor` power/link LEDs
   before restarting anything.

5. If a change is later authorized, prefer logging the current `ng-2ndfloor`
   mesh state immediately before and after the change so the effect is
   attributable.
