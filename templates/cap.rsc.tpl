# {{IDENTITY}}: {{MODEL}}, CAP (точка доступу під керуванням CAPsMAN на RB4011)
# Згенеровано generate.py зі шаблону templates/cap.rsc.tpl. Не редагуйте цей файл, змінюйте шаблон або .env.
# Потрібно: RouterOS 7.24.5 (та сама версія, що й на RB4011), увімкнений пакет {{WIFI_PACKAGE}}.
# Застосовувати лише на щойно скинутому роутері (скрипт не ідемпотентний), див. README.md.
#
# Як застосувати: завантажте цей файл у Files на роутері (WinBox: перетягнути), потім виконайте в терміналі:
#   /system reset-configuration no-defaults=yes skip-backup=yes run-after-reset={{IDENTITY}}.rsc

/system identity set name={{IDENTITY}}

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
/user set admin password="{{ADMIN_PASSWORD}}"

# Підключення до CAPsMAN: радіо мають бути увімкнені й передані контролеру,
# інакше вони лишаються вимкненими і контролер про них не знає
/interface wifi set [find] configuration.manager=capsman disabled=no
/interface wifi cap set enabled=yes discovery-interfaces=bridge slaves-static=no
