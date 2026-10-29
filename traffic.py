#!/usr/bin/env python3
"""Показує, який пристрій до якої точки доступу підключений і яке навантаження він створює.

Скрипт підключається до RB4011 по SSH і за один сеанс виконує лише команди читання (print):
  - /interface wifi registration-table: усі Wi-Fi клієнти (і RB4011, і точок під CAPsMAN) з лічильниками байтів;
  - /interface print stats-detail: лічильники портів RB4011, в які увімкнені точки доступу, і коментарі
    "operated by CAP <MAC>", які пов'язують радіо cap-wifiN з точкою;
  - /interface wifi capsman remote-cap, /interface bridge host, /ip dhcp-server lease: імена точок, їхні порти й IP клієнтів.
Лічильники знімаються двічі з паузою між зрізами, швидкість це різниця байтів поділена на час.

TX: від точки до пристрою (завантаження на пристрій), RX: від пристрою до точки (вивантаження з пристрою).
Для дротових пристроїв за точкою доступу окремих лічильників немає: їхнє навантаження входить у рядок
"порт" точки (трафік порту RB4011 до точки), де також видно сумарний Wi-Fi трафік.

Використання:
    python3 traffic.py [--host 192.168.89.1] [--user admin] [--duration 30]
    python3 traffic.py --show-zeros         # показати й клієнтів без трафіку (за замовчуванням вони приховані)
    python3 traffic.py --max-only           # одна таблиця: 10 найактивніших клієнтів за TX, точка в окремій колонці
    python3 traffic.py --max-only --source ax3-1   # те саме, але лише клієнти однієї точки
    python3 traffic.py --raw sample.txt     # зберегти сирий вивід роутера у файл
    python3 traffic.py --input sample.txt   # не підключатися до роутера, а розібрати збережений вивід

Пароль SSH запитує сам ssh. Залежностей немає, потрібен лише Python 3 і ssh.
"""
import argparse
import re
import subprocess
import sys

KV_RE = re.compile(r'([\w.-]+)=("(?:[^"\\]|\\.)*"|\S*)')
RECORD_START_RE = re.compile(r"^\s{0,3}\d+\s")
SECTION_RE = re.compile(r"^###(\w+)$")
CAP_COMMENT_RE = re.compile(r";;; operated by CAP ([0-9A-Fa-f:]{17})")
INTERFACE_BYTES_RE = re.compile(r"rx-byte=([\d ]+?)\s+tx-byte=([\d ]+?)\s+rx-packet")
ROUTER_NAME = "rb4011"


def build_command(duration):
    """Одна команда RouterOS: перший зріз, пауза, другий зріз. Усі print-команди лише читають."""
    registration = "/interface wifi registration-table print stats without-paging"
    interfaces = "/interface print stats-detail without-paging"
    return (
        ':put "###static_caps"; /interface wifi capsman remote-cap print terse without-paging; '
        ':put "###static_hosts"; /interface bridge host print terse without-paging where !local; '
        ':put "###static_leases"; /ip dhcp-server lease print terse without-paging; '
        ':put "###reg1"; %s; :put "###if1"; %s; '
        ":delay %ds; "
        ':put "###reg2"; %s; :put "###if2"; %s; :put "###end"'
    ) % (registration, interfaces, duration, registration, interfaces)


def run_router(host, user, duration):
    command = build_command(duration)
    ssh = ["ssh", "-o", "ConnectTimeout=10", "%s@%s" % (user, host), command]
    try:
        # stdin і stderr лишаються підключеними до термінала, щоб ssh міг запитати пароль
        completed = subprocess.run(ssh, stdout=subprocess.PIPE, universal_newlines=True, timeout=duration + 60)
    except FileNotFoundError:
        raise SystemExit("Не знайдено команду ssh. Встановіть клієнт OpenSSH.")
    except subprocess.TimeoutExpired:
        raise SystemExit("Роутер не відповів вчасно. Спробуйте ще раз.")
    if completed.returncode != 0 and not completed.stdout.strip():
        raise SystemExit("ssh завершився з кодом %d, виводу немає." % completed.returncode)
    return completed.stdout


def split_sections(text):
    sections = {}
    current = None
    for line in text.replace("\r", "").split("\n"):
        match = SECTION_RE.match(line.strip())
        if match:
            current = match.group(1)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def unescape(value):
    """RouterOS записує не-ASCII символи в лапках як \\XX (байти UTF-8 у hex): "\\D0\\97\\D0\\B0\\D0\\BB" це "Зал"."""
    if "\\" not in value:
        return value
    raw = re.sub(r"\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), value)
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def parse_fields(text):
    fields = {}
    for key, value in KV_RE.findall(text):
        fields[key] = unescape(value[1:-1]) if value.startswith('"') else value
    return fields


def parse_records(lines):
    """Розбирає вивід print (detail/stats): запис починається з рядка з номером, продовження мають відступ."""
    records = []
    for line in lines:
        if RECORD_START_RE.match(line):
            records.append(line.strip())
        elif records and line.strip():
            records[-1] += " " + line.strip()
    return records


def parse_terse(lines):
    return [parse_fields(record) for record in parse_records(lines)]


def parse_registration(lines):
    """Повертає {mac: {interface, signal, band, tx_bytes, rx_bytes}}."""
    clients = {}
    for record in parse_records(lines):
        fields = parse_fields(record)
        mac = fields.get("mac-address", "").upper()
        if not mac:
            continue
        tx_bytes = rx_bytes = 0
        if "bytes" in fields and "," in fields["bytes"]:
            tx_text, rx_text = fields["bytes"].split(",", 1)
            tx_bytes, rx_bytes = int(tx_text), int(rx_text)
        clients[mac] = {
            "interface": fields.get("interface", ""),
            "signal": fields.get("signal", ""),
            "band": fields.get("band", ""),
            "tx_bytes": tx_bytes,
            "rx_bytes": rx_bytes,
        }
    return clients


def parse_interfaces(lines):
    """Повертає ({назва інтерфейсу: (rx_byte, tx_byte)}, {cap-wifiN: MAC точки})."""
    counters = {}
    cap_of_radio = {}
    for record in parse_records(lines):
        fields = parse_fields(record)
        name = fields.get("name")
        if not name:
            continue
        match = INTERFACE_BYTES_RE.search(record)
        if match:
            counters[name] = (int(match.group(1).replace(" ", "")), int(match.group(2).replace(" ", "")))
        cap_match = CAP_COMMENT_RE.search(record)
        if cap_match:
            cap_of_radio[name] = cap_match.group(1).upper()
    return counters, cap_of_radio


def rate(before, after, seconds):
    """Біти за секунду; None, якщо лічильник скинувся (клієнт перепідключився)."""
    if after < before:
        return None
    return (after - before) * 8 / seconds


def format_rate(bps):
    if bps is None:
        return "-"
    for unit, divisor in (("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        if bps >= divisor:
            return "%.1f%s" % (bps / divisor, unit)
    return "%.0fbps" % bps


def analyze(text, duration):
    """Повертає список точок: {name, ip, port, port_tx, port_rx, wifi: [...], wired: [...]}."""
    sections = split_sections(text)
    if "reg2" not in sections or "if2" not in sections:
        raise SystemExit("У виводі роутера немає другого зрізу лічильників (вивід обірвано?).")
    return analyze_sections(sections, duration)


def analyze_sections(sections, duration):
    """Те саме, що analyze, але з уже розібраними секціями (static_*, reg1/if1 і reg2/if2)."""
    caps = parse_terse(sections.get("static_caps", []))
    hosts = parse_terse(sections.get("static_hosts", []))
    leases = parse_terse(sections.get("static_leases", []))
    registration1 = parse_registration(sections.get("reg1", []))
    registration2 = parse_registration(sections.get("reg2", []))
    interfaces1, _ = parse_interfaces(sections.get("if1", []))
    interfaces2, cap_of_radio = parse_interfaces(sections.get("if2", []))

    lease_of_mac = {lease["mac-address"].upper(): lease for lease in leases if "mac-address" in lease}
    port_of_mac = {host["mac-address"].upper(): host.get("on-interface", "") for host in hosts if "mac-address" in host}

    aps = {}
    aps[ROUTER_NAME] = {"name": ROUTER_NAME, "mac": None, "port": None, "wifi": [], "wired": []}
    for cap in caps:
        mac = cap.get("base-mac", "").upper()
        aps[mac] = {"name": cap.get("identity", mac), "mac": mac, "port": port_of_mac.get(mac), "wifi": [], "wired": []}
    for key, ap in aps.items():
        lease = lease_of_mac.get(ap["mac"]) if ap["mac"] else None
        ap["ip"] = lease["address"] if lease else None
        port = ap["port"]
        if port and port in interfaces1 and port in interfaces2:
            ap["port_tx"] = rate(interfaces1[port][1], interfaces2[port][1], duration)
            ap["port_rx"] = rate(interfaces1[port][0], interfaces2[port][0], duration)
        else:
            ap["port_tx"] = ap["port_rx"] = None

    def describe(mac):
        lease = lease_of_mac.get(mac)
        return (lease.get("host-name") or mac) if lease else mac, (lease["address"] if lease else "")

    ap_macs = {ap["mac"] for ap in aps.values() if ap["mac"]}
    port_to_ap = {ap["port"]: ap for ap in aps.values() if ap["port"]}

    for mac, client in registration2.items():
        if mac in ap_macs:
            continue
        radio = client["interface"]
        ap = aps[cap_of_radio[radio]] if radio in cap_of_radio and cap_of_radio[radio] in aps else None
        if ap is None and radio in cap_of_radio:
            continue  # радіо належить точці, яку CAPsMAN вже не знає
        if ap is None:
            ap = aps[ROUTER_NAME]
        before = registration1.get(mac)
        tx = rx = None
        if before:
            tx = rate(before["tx_bytes"], client["tx_bytes"], duration)
            rx = rate(before["rx_bytes"], client["rx_bytes"], duration)
        name, ip = describe(mac)
        ap["wifi"].append({"name": name, "ip": ip, "mac": mac, "band": client["band"], "signal": client["signal"],
                           "tx": tx, "rx": rx})

    # Дротові: хости на порті точки, яких немає серед Wi-Fi клієнтів і які не є самими точками
    for mac, port in port_of_mac.items():
        if mac in registration2 or mac in ap_macs or port not in port_to_ap:
            continue
        name, ip = describe(mac)
        port_to_ap[port]["wired"].append({"name": name, "ip": ip, "mac": mac})

    result = list(aps.values())
    for ap in result:
        ap["wifi"].sort(key=lambda c: (c["tx"] or 0) + (c["rx"] or 0), reverse=True)
    return result


def is_idle(client):
    """Клієнт без трафіку: TX і RX округлюються до 0bps (або швидкість невідома)."""
    return round(client["tx"] or 0) == 0 and round(client["rx"] or 0) == 0


def print_table(header, rows, indent, left_columns):
    """Друкує таблицю: перші left_columns колонок вирівняні вліво, решта вправо."""
    widths = [max(len(str(row[i])) for row in [header] + rows) for i in range(len(header))]
    for row in [header] + rows:
        cells = [str(row[i]).ljust(widths[i]) if i < left_columns else str(row[i]).rjust(widths[i])
                 for i in range(len(header))]
        print(indent + "  ".join(cells))


def select_source(aps, source):
    """Повертає точну назву точки за введеною (без урахування регістру) або завершує роботу з переліком доступних."""
    names = [ap["name"] for ap in aps]
    for name in names:
        if name.lower() == source.strip().lower():
            return name
    raise SystemExit("Точку %r не знайдено. Доступні: %s" % (source, ", ".join(names)))


def print_max_only(aps, duration, limit=10, source=None):
    if source:
        source = select_source(aps, source)
    clients = [(ap["name"], c) for ap in aps for c in ap["wifi"] if not source or ap["name"] == source]
    clients.sort(key=lambda item: item[1]["tx"] or 0, reverse=True)
    print("Навантаження за %d с, топ-%d клієнтів за TX%s. TX: до пристрою (завантаження), RX: від пристрою (вивантаження).\n"
          % (duration, limit, " на точці " + source if source else ""))
    rows = [(c["name"], c["ip"], ap_name, c["band"], c["signal"], format_rate(c["tx"]), format_rate(c["rx"]))
            for ap_name, c in clients[:limit]]
    print_table(("Пристрій", "IP", "Точка", "Діапазон", "Сигнал", "TX", "RX"), rows, "", 5)


def print_report(aps, duration, host, show_zeros):
    print("Навантаження за %d с. TX: до пристрою (завантаження), RX: від пристрою (вивантаження).\n" % duration)
    for ap in aps:
        title = ap["name"] + (" (%s)" % ap["ip"] if ap["ip"] else " (%s)" % host if ap["name"] == ROUTER_NAME else "")
        wifi_tx = sum(c["tx"] or 0 for c in ap["wifi"])
        wifi_rx = sum(c["rx"] or 0 for c in ap["wifi"])
        shown = ap["wifi"] if show_zeros else [c for c in ap["wifi"] if not is_idle(c)]
        print(title)
        if ap["port"]:
            print("  порт %s до точки: TX %s, RX %s" % (ap["port"], format_rate(ap["port_tx"]), format_rate(ap["port_rx"])))
        print("  Wi-Fi клієнтів: %d, разом TX %s, RX %s" % (len(ap["wifi"]), format_rate(wifi_tx), format_rate(wifi_rx)))
        if shown:
            rows = [(c["name"], c["ip"], c["band"], c["signal"], format_rate(c["tx"]), format_rate(c["rx"])) for c in shown]
            print_table(("Пристрій", "IP", "Діапазон", "Сигнал", "TX", "RX"), rows, "    ", 4)
        hidden = len(ap["wifi"]) - len(shown)
        if hidden:
            print("    ще %d без трафіку приховано (--show-zeros)" % hidden)
        if ap["wired"]:
            print("  Дротові (або без запису в Wi-Fi), окремих лічильників немає:")
            for client in ap["wired"]:
                print("    %s  %s  %s" % (client["name"], client["ip"], client["mac"]))
        print()


def main():
    parser = argparse.ArgumentParser(description="Які пристрої до якої точки підключені і яке навантаження вони створюють")
    parser.add_argument("--host", default="192.168.89.1", help="адреса RB4011 (за замовчуванням 192.168.89.1)")
    parser.add_argument("--user", default="admin", help="користувач SSH (за замовчуванням admin)")
    parser.add_argument("--duration", type=int, default=30, help="тривалість вимірювання, секунди (за замовчуванням 30)")
    parser.add_argument("--show-zeros", action="store_true", help="показувати й клієнтів, у яких TX і RX дорівнюють 0bps")
    parser.add_argument("--max-only", action="store_true",
                        help="одна таблиця з 10 клієнтами з найбільшим TX, точка доступу в окремій колонці")
    parser.add_argument("--source", metavar="ТОЧКА",
                        help="з --max-only: лише клієнти цієї точки (rb4011, ac3-1, ax3-2, ...)")
    parser.add_argument("--raw", metavar="ФАЙЛ", help="зберегти сирий вивід роутера у файл")
    parser.add_argument("--input", metavar="ФАЙЛ", help="не підключатися до роутера, а розібрати збережений вивід")
    args = parser.parse_args()

    if args.duration < 1 or args.duration > 300:
        parser.error("--duration має бути від 1 до 300 секунд")
    if args.source and not args.max_only:
        parser.error("--source працює лише разом з --max-only")

    if args.input:
        with open(args.input, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    else:
        print("Вимірюю трафік %d с на %s..." % (args.duration, args.host), file=sys.stderr)
        text = run_router(args.host, args.user, args.duration)
    if args.raw:
        with open(args.raw, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("Сирий вивід збережено в %s" % args.raw, file=sys.stderr)

    aps = analyze(text, args.duration)
    if args.max_only:
        print_max_only(aps, args.duration, source=args.source)
    else:
        print_report(aps, args.duration, args.host, args.show_zeros)
    return 0


if __name__ == "__main__":
    sys.exit(main())
