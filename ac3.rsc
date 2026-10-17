# hAP ac3: CAP (access point managed by CAPsMAN on RB4011)
# Needs: RouterOS 7.24.5, package wifi-qcom-ac enabled (same version as the RB4011).
# Apply to a freshly reset router only (not idempotent), see README.md.
# BEFORE USE: change the admin password, and set a unique identity for each device (ac3-1, ac3-2, ...).

/system identity set name=ac3-1

# Bridge: all ports act as a switch
/interface bridge add name=bridge protocol-mode=rstp
/interface bridge port
add bridge=bridge interface=ether1
add bridge=bridge interface=ether2
add bridge=bridge interface=ether3
add bridge=bridge interface=ether4
add bridge=bridge interface=ether5
# CAPsMAN-managed radios are not added to the bridge automatically (datapath.bridge is not
# applied on this CAP), so add them here. Without this Wi-Fi clients get no DHCP lease.
add bridge=bridge interface=wifi1
add bridge=bridge interface=wifi2

# Management address from RB4011 DHCP
/ip dhcp-client add interface=bridge

# Hardening
/interface list add name=LAN
/interface list member add list=LAN interface=bridge
/ip service disable telnet,ftp,www,api,api-ssl
/ip neighbor discovery-settings set discover-interface-list=LAN
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/user set admin password=""

# Join CAPsMAN: radios must be enabled and handed to the controller,
# otherwise they stay disabled and are never reported to CAPsMAN
/interface wifi set [find] configuration.manager=capsman disabled=no
/interface wifi cap set enabled=yes discovery-interfaces=bridge slaves-static=no
