# {{IDENTITY}}: роутер + контролер CAPsMAN + власне радіо (5 ГГц) як частина мережі
# Згенеровано generate.py зі шаблону templates/rb4011.rsc.tpl. Не редагуйте цей файл, змінюйте шаблон або .env.
# Потрібно: RouterOS 7.24.5, увімкнений пакет wifi-qcom-ac. Підмережа 192.168.89.0/24
# Застосовувати лише на щойно скинутому роутері (скрипт не ідемпотентний), див. README.md.
# Wi-Fi: {{WIFI_MODE}}
#
# Як застосувати:
#   1. Збережіть резервну копію поточної конфігурації (з паролями у відкритому вигляді) і завантажте її на комп'ютер
#      (WinBox: Files, перетягнути), бо скидання нижче все стирає:
#        /export show-sensitive file=backup-{{IDENTITY}}
#   2. Завантажте цей файл у Files на роутері (WinBox: перетягнути).
#   3. Виконайте в терміналі:
#        /system reset-configuration no-defaults=yes skip-backup=yes run-after-reset={{IDENTITY}}.rsc

/system identity set name={{IDENTITY}}

# Міст і порти (ether1 = WAN)
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

# Списки інтерфейсів
/interface list add name=LAN
/interface list add name=WAN
/interface list member add list=LAN interface=bridge
/interface list member add list=WAN interface=ether1

# IP, DHCP, DNS
/ip address add address=192.168.89.1/24 interface=bridge
# Адреси LAN поза цим пулом (крім .1, його займає роутер) можна віддавати пристроям зі статичними адресами
/ip pool add name=pool-lan ranges={{POOL_RANGE}}
/ip dhcp-server add name=dhcp-lan interface=bridge address-pool=pool-lan lease-time=1h
/ip dhcp-server network add address=192.168.89.0/24 gateway=192.168.89.1 dns-server=192.168.89.1
/ip dns set allow-remote-requests=yes servers=1.1.1.1,8.8.8.8
/ip dhcp-client add interface=ether1 use-peer-dns=no add-default-route=yes

# NAT
/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade

# Файрвол
/ip firewall filter
add chain=input action=accept connection-state=established,related,untracked
add chain=input action=drop connection-state=invalid
add chain=input action=accept protocol=icmp
add chain=input action=accept in-interface-list=LAN
add chain=input action=drop
add chain=forward action=fasttrack-connection connection-state=established,related
add chain=forward action=accept connection-state=established,related,untracked
add chain=forward action=drop connection-state=invalid
add chain=forward action=drop connection-state=new connection-nat-state=!dstnat in-interface-list=WAN

# Захист (hardening)
/ip service disable telnet,ftp,www,api,api-ssl
/ip neighbor discovery-settings set discover-interface-list=LAN
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/user set admin password="{{ADMIN_PASSWORD}}"

# Wi-Fi (CAPsMAN)
# Коротка пауза, щоб пакет wifi повністю завантажився при запуску через run-after-reset
:delay 5s
/interface wifi datapath add name=dp-lan bridge=bridge
/interface wifi security add name=sec-main authentication-types=wpa2-psk,wpa3-psk passphrase="{{WIFI_PASSWORD}}" ft=yes ft-over-ds=yes
# Канал 5 ГГц без DFS-каналів: радіо не чекає 1-10 хвилин перевірки на радари після кожного запуску
# і не змінює канал, коли виявляє радар. Каналів менше, зате мережа стабільна й з'являється одразу.
# Ширину каналу й стандарт (band) не задаємо: за замовчуванням радіо саме обирає найкращі,
# а band=5ghz-ac утримував би ax-радіо hAP ax3 на швидкостях Wi-Fi 5.
/interface wifi channel
add name=ch-5g skip-dfs-channels=all
/interface wifi configuration
# Режим мережі задає generate.py: SSID_5G дорівнює SSID_2G (одна мережа) або має суфікс -5g (окремі мережі)
add name=cfg-2g ssid="{{SSID_2G}}" country="{{COUNTRY}}" security=sec-main datapath=dp-lan steering.rrm=yes steering.wnm=yes
add name=cfg-5g ssid="{{SSID_5G}}" country="{{COUNTRY}}" security=sec-main datapath=dp-lan steering.rrm=yes steering.wnm=yes channel=ch-5g
/interface wifi provisioning
# Правила використовують лише діапазони n та ac: їх підтримують і hAP ac3 (без ax), і hAP ax3.
# Правило підходить лише радіо, яке підтримує всі вказані діапазони, тому ax у списку не вказуємо.
add action=create-dynamic-enabled supported-bands=2ghz-n master-configuration=cfg-2g
add action=create-dynamic-enabled supported-bands=5ghz-ac master-configuration=cfg-5g
/interface wifi capsman set enabled=yes interfaces=bridge upgrade-policy=none

# Власне радіо RB4011 (wifi1, лише 5 ГГц) теж роздає цю мережу, тож RB4011 є частиною мережі.
# Воно налаштовується напряму тією самою конфігурацією, що й радіо точок доступу, без CAPsMAN:
# режим capsman-or-local не підключав радіо до локального CAPsMAN, і воно лишалося без SSID.
# Цей рядок стоїть у кінці файлу навмисно: якщо він не виконається, решта конфігурації вже застосована.
# До моста радіо додається саме (datapath dp-lan має bridge=bridge).
/interface wifi set wifi1 configuration=cfg-5g configuration.manager=local disabled=no
