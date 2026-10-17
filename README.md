# MikroTik Wi-Fi mesh

Wired-backhaul Wi-Fi mesh: an RB4011 is the router and CAPsMAN controller, and one or more hAP ac3 units are managed access points (CAPs).

| File | Device | Role |
|---|---|---|
| [rb4011.rsc](rb4011.rsc) | RB4011iGS+5HacQ2HnD | Router, DHCP/DNS, NAT, firewall, CAPsMAN controller |
| [ac3.rsc](ac3.rsc) | hAP ac3 (one or more) | CAP: bridged switch + radios managed by the RB4011 |

## Network

- LAN `192.168.89.0/24`, router `192.168.89.1`, DHCP pool `.100`-`.254`.
- `ether1` on the RB4011 is the WAN (DHCP client). Everything else is bridged into the LAN.
- SSIDs: `TP-Link_7D15` (2.4 GHz) and `TP-Link_7D15-5g` (5 GHz), WPA2/WPA3-PSK, 802.11r/k/v roaming enabled.
- Each ac3 connects to an RB4011 LAN port by cable, gets a management address by DHCP and joins CAPsMAN over the bridge.

## Requirements

- RouterOS **7.24.5** on all devices (use the same version everywhere).
- Package `wifi-qcom-ac` installed and enabled, and `wireless` disabled. Check with `/system package print`. Packages survive a configuration reset.

## Before you start

The scripts contain a plaintext admin password and Wi-Fi passphrase. Change them (`/user set admin password=...` in both files, `passphrase=...` in [rb4011.rsc](rb4011.rsc)) before using them on real devices, and don't push the repo anywhere public with real values in it.

Each ac3 needs its own identity. Edit the `/system identity set name=ac3-1` line in a copy of [ac3.rsc](ac3.rsc) (ac3-2, ac3-3, ...), or run `/system identity set name=ac3-2` after the reset.

## Apply a script

The scripts are meant for a freshly reset router and are not idempotent. Running one twice fails on duplicate entries.

1. Upload the `.rsc` file to the router's root file list (WinBox: Files, drag and drop; or `scp rb4011.rsc admin@<router>:`).
2. Reset the router and run the file afterwards:
   ```
   /system reset-configuration no-defaults=yes skip-backup=yes run-after-reset=rb4011.rsc
   ```
   Use `run-after-reset=ac3.rsc` on an ac3.
3. Wait for the reboot. The script runs on first boot.

The reset wipes the router's IP configuration, so reconnect with MAC-WinBox (or a cable and a static IP) if needed. The RB4011 comes back on `192.168.89.1` once the script has run.

### Order

Set up the RB4011 first, then the ac3 units. The order is forgiving, but this is the smooth path:

- The ac3 gets its management address from the RB4011 DHCP server and discovers the CAPsMAN controller over the bridge, so both need to be up.
- If you configure an ac3 first, nothing breaks. Its script doesn't depend on the RB4011. Once the RB4011 is up the ac3 should get an address and join on its own, which can take a minute or two. Unplugging and replugging the cable speeds it up.
- Connect each ac3 to a LAN port on the RB4011 (ether2-10 or the SFP+ port), never to ether1 (WAN).
- You can reset an ac3 with the cable unplugged and plug it in after the RB4011 script has finished.
- After the ac3 joins, it appears in `/interface wifi capsman remote-cap print` on the RB4011, and the dynamic `cap-wifi` interfaces lose the `X` (disabled) flag.

If the script stops partway, everything before the failing line stays applied. Look at `/log print` for the error.

## Verify

On the RB4011:

```
/ip dhcp-client print                       # ether1 bound
/ping 1.1.1.1 count=3
/interface wifi capsman print               # enabled: yes
/interface wifi capsman remote-cap print    # each ac3 listed, state Ok
/interface wifi radio print                 # local radio plus two radios per ac3
/interface wifi print                       # cap-wifi1, cap-wifi2 ... not flagged X
/interface wifi registration-table print    # connected Wi-Fi clients
```

On an ac3:

```
/ip dhcp-client print                       # bridge bound, 192.168.89.x
/interface wifi cap print                   # enabled: yes
/interface wifi print                       # radios no longer disabled
/log print where topics~"wifi"
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `capsman print` says `enabled: no`, and configuration/provisioning/security are empty | The import stopped before the Wi-Fi section. Check `/log print` and re-run the missing lines. |
| ac3 listed in `remote-cap` but no radios in `/interface wifi radio print` | The ac3 radios are disabled or not handed to CAPsMAN. On the ac3: `/interface wifi set [find] configuration.manager=capsman disabled=no` (already in [ac3.rsc](ac3.rsc)). |
| `cap-wifi1/2` appear but stay disabled (`X`) | The provisioning rules don't match the radio bands. The ac3 radios are 802.11ac and have no `ax`; a rule only matches radios supporting every listed band. Check `/interface wifi radio print detail`. |
| CAP never joins | Different RouterOS versions, missing `wifi-qcom-ac`, or the ac3 isn't on the same bridge/LAN as the RB4011. |

## Notes

- The RB4011's own radio (`wifi1`) is not managed by CAPsMAN and stays disabled. Enable it and set `configuration.manager=capsman-or-local` if you want it to serve the same SSIDs.
- Firewall: the RB4011 accepts input only from the LAN and from established connections, and blocks new connections from the WAN. Services other than SSH and WinBox are disabled, and neighbor discovery and MAC-server access are limited to the LAN.
