# hAP ac3: CAP (точка доступу під керуванням CAPsMAN на RB4011)
# Потрібно: RouterOS 7.24.5, увімкнений пакет wifi-qcom-ac (та сама версія, що й на RB4011).
# Застосовувати лише на щойно скинутому роутері (скрипт не ідемпотентний), див. README.md.
# ПЕРЕД ВИКОРИСТАННЯМ: змініть пароль admin і задайте унікальне ім'я для кожного пристрою (ac3-1, ac3-2, ...).

/system identity set name=ac3-1

# Міст: усі порти працюють як комутатор
/interface bridge add name=bridge protocol-mode=rstp
/interface bridge port
add bridge=bridge interface=ether1
add bridge=bridge interface=ether2
add bridge=bridge interface=ether3
add bridge=bridge interface=ether4
add bridge=bridge interface=ether5
# Радіо під керуванням CAPsMAN не додаються в міст автоматично (datapath.bridge на цьому CAP не застосовується),
# тому додаємо їх тут. Без цього Wi-Fi клієнти не отримують DHCP-адресу.
add bridge=bridge interface=wifi1
add bridge=bridge interface=wifi2

# Адреса керування з DHCP на RB4011
/ip dhcp-client add interface=bridge

# Захист (hardening)
/interface list add name=LAN
/interface list member add list=LAN interface=bridge
/ip service disable telnet,ftp,www,api,api-ssl
/ip neighbor discovery-settings set discover-interface-list=LAN
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/user set admin password=""

# Підключення до CAPsMAN: радіо мають бути увімкнені й передані контролеру,
# інакше вони лишаються вимкненими і контролер про них не знає
/interface wifi set [find] configuration.manager=capsman disabled=no
/interface wifi cap set enabled=yes discovery-interfaces=bridge slaves-static=no
