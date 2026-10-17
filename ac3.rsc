# hAP ac3: CAP (access point managed by CAPsMAN on RB4011)
# Needs: RouterOS 7, package wifi-qcom-ac enabled.
# BEFORE USE: change ADMIN_PASSWORD, and set a unique identity for each device (ac3-1, ac3-2, ...).

/system identity set name=ac3-1

# Bridge: all ports act as a switch
/interface bridge add name=bridge protocol-mode=rstp
/interface bridge port
add bridge=bridge interface=ether1
add bridge=bridge interface=ether2
add bridge=bridge interface=ether3
add bridge=bridge interface=ether4
add bridge=bridge interface=ether5

# Management address from RB4011 DHCP
/ip dhcp-client add interface=bridge

# Hardening
/interface list add name=LAN
/interface list member add list=LAN interface=bridge
/ip service disable telnet,ftp,www,api,api-ssl
/ip neighbor discovery-settings set discover-interface-list=LAN
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/user set admin password="ADMIN_PASSWORD"

# Join CAPsMAN
/interface wifi cap set enabled=yes discovery-interfaces=bridge slaves-static=no
