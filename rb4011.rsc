# RB4011: router + CAPsMAN controller
# Needs: RouterOS 7.24.5, package wifi-qcom-ac enabled. Subnet 192.168.89.0/24
# Apply to a freshly reset router only (not idempotent), see README.md.
# BEFORE USE: change the admin password (/user set) and the Wi-Fi passphrase below.

/system identity set name=rb4011

# Bridge and ports (ether1 = WAN)
/interface bridge add name=bridge protocol-mode=rstp
/interface bridge port
add bridge=bridge interface=ether2
add bridge=bridge interface=ether3
add bridge=bridge interface=ether4
add bridge=bridge interface=ether5
add bridge=bridge interface=ether6
add bridge=bridge interface=ether7
add bridge=bridge interface=ether8
add bridge=bridge interface=ether9
add bridge=bridge interface=ether10
add bridge=bridge interface=sfp-sfpplus1

# Interface lists
/interface list add name=LAN
/interface list add name=WAN
/interface list member add list=LAN interface=bridge
/interface list member add list=WAN interface=ether1

# IP, DHCP, DNS
/ip address add address=192.168.89.1/24 interface=bridge
/ip pool add name=pool-lan ranges=192.168.89.100-192.168.89.254
/ip dhcp-server add name=dhcp-lan interface=bridge address-pool=pool-lan lease-time=1h
/ip dhcp-server network add address=192.168.89.0/24 gateway=192.168.89.1 dns-server=192.168.89.1
/ip dns set allow-remote-requests=yes servers=1.1.1.1,8.8.8.8
/ip dhcp-client add interface=ether1 use-peer-dns=no add-default-route=yes

# NAT
/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade

# Firewall
/ip firewall filter
add chain=input action=accept connection-state=established,related,untracked
add chain=input action=drop connection-state=invalid
add chain=input action=accept protocol=icmp
add chain=input action=accept in-interface-list=LAN
add chain=input action=drop
add chain=forward action=fasttrack-connection hw-offload=yes connection-state=established,related
add chain=forward action=accept connection-state=established,related,untracked
add chain=forward action=drop connection-state=invalid
add chain=forward action=drop connection-state=new connection-nat-state=!dstnat in-interface-list=WAN

# Hardening
/ip service disable telnet,ftp,www,api,api-ssl
/ip neighbor discovery-settings set discover-interface-list=LAN
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/user set admin password=""

# Wi-Fi (CAPsMAN)
# Short pause so the wifi package is fully loaded when run via run-after-reset
:delay 5s
/interface wifi datapath add name=dp-lan bridge=bridge
/interface wifi security add name=sec-main authentication-types=wpa2-psk,wpa3-psk passphrase="" ft=yes ft-over-ds=yes
/interface wifi configuration
add name=cfg-2g ssid="TP-Link_7D15" country=Ukraine security=sec-main datapath=dp-lan steering.rrm=yes steering.wnm=yes
add name=cfg-5g ssid="TP-Link_7D15-5g" country=Ukraine security=sec-main datapath=dp-lan steering.rrm=yes steering.wnm=yes
/interface wifi provisioning
# hAP ac3 radios are 802.11ac (no ax): a rule only matches radios supporting every listed band
add action=create-dynamic-enabled supported-bands=2ghz-n master-configuration=cfg-2g
add action=create-dynamic-enabled supported-bands=5ghz-ac master-configuration=cfg-5g
/interface wifi capsman set enabled=yes interfaces=bridge upgrade-policy=none
