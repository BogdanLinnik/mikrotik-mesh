#!/usr/bin/env python3
"""Підсумок навантаження на мережу по пристроях на основі /tool torch на роутері.

Скрипт запускає на RB4011 по SSH команду
    /tool torch interface=bridge src-address=0.0.0.0/0 dst-address=0.0.0.0/0 ip-protocol=any duration=10s
розбирає її вивід (Torch оновлює таблицю щосекунди), групує потоки за IP-PROTOCOL і SRC-ADDRESS
і підсумовує TX та RX. Результат: середня швидкість за час вимірювання, найбільші зверху.

Torch показує швидкості в бітах за секунду. За документацією MikroTik SRC-ADDRESS це "далекий" від
інтерфейсу бік потоку, RX це швидкість від нього, а TX швидкість до нього. Для моста з пристроями
LAN це означає: TX це завантаження на пристрій, RX це вивантаження з пристрою.

Використання:
    python3 traffic.py [--host 192.168.89.1] [--user admin] [--duration 10] [--top 20]
    python3 traffic.py --raw sample.txt     # зберегти сирий вивід Torch у файл (для перевірки розбору)
    python3 traffic.py --input sample.txt   # не підключатися до роутера, а розібрати збережений вивід

Пароль SSH запитує сам ssh. Щоб не вводити його щоразу, додайте на роутер ключ SSH.
Залежностей немає, потрібен лише Python 3 і ssh.
"""
import argparse
import ipaddress
import re
import subprocess
import sys
from collections import Counter, defaultdict

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-B0-2]|\r")
RATE_RE = re.compile(r"^(\d+(?:\.\d+)?)(bps|kbps|Mbps|Gbps)$", re.IGNORECASE)
RATE_UNITS = {"bps": 1, "kbps": 1e3, "mbps": 1e6, "gbps": 1e9}
INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_rate(token):
    """Повертає швидкість у бітах за секунду або None, якщо токен не є швидкістю (2.0Mbps, 340kbps, 0bps)."""
    match = RATE_RE.match(token)
    if not match:
        return None
    return float(match.group(1)) * RATE_UNITS[match.group(2).lower()]


def format_rate(bps):
    for unit, divisor in (("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        if bps >= divisor:
            return "%.1f%s" % (bps / divisor, unit)
    return "%.0fbps" % bps


def parse_line(line):
    """Розбирає один рядок Torch. Повертає (ключ потоку, ip-protocol, src, tx, rx) або None.

    Приклад рядка: "ip udp 0 192.168.88.20 2257 192.168.88.1 2001 (glimpse) 2.0Mbps 0bps 172 0".
    Колонки визначаються не за позицією, а за виглядом токенів: перші дві адреси IPv4 це SRC і DST,
    перші дві швидкості це TX і RX, а IP-PROTOCOL це другий токен після MAC-PROTOCOL "ip".
    """
    tokens = line.split()
    if len(tokens) < 6 or tokens[0].lower() != "ip":
        return None
    addresses = []
    rates = []
    for token in tokens[2:]:
        try:
            addresses.append(str(ipaddress.IPv4Address(token)))
            continue
        except ValueError:
            pass
        rate = parse_rate(token)
        if rate is not None:
            rates.append((token, rate))
    if len(addresses) < 2 or len(rates) < 2:
        return None
    # Ключ потоку: усе до першої швидкості, щоб відрізнити однакові потоки в різних кадрах таблиці
    first_rate_token = rates[0][0]
    key = tuple(tokens[: tokens.index(first_rate_token, 2)])
    return key, tokens[1].lower(), addresses[0], rates[0][1], rates[1][1]


def summarize(text, subnet=None):
    """Групує рядки за (IP-PROTOCOL, SRC-ADDRESS) і усереднює TX та RX за кадри таблиці.

    Torch друкує повну таблицю щосекунди, тому потік зустрічається один раз на кадр. Кількість кадрів
    оцінюється як найбільша кількість появ одного потоку. Потік, якого в кадрі немає, рахується як нуль.
    Повертає (список (протокол, адреса, tx, rx), кількість кадрів, кількість розібраних рядків).
    """
    rows = []
    for raw_line in ANSI_RE.sub("\n", text).split("\n"):
        parsed = parse_line(raw_line)
        if parsed:
            rows.append(parsed)
    if not rows:
        return [], 0, 0

    frames = max(Counter(key for key, *_ in rows).values())
    totals = defaultdict(lambda: [0.0, 0.0])
    for _, protocol, src, tx, rx in rows:
        if subnet is not None and ipaddress.IPv4Address(src) not in subnet:
            continue
        totals[(protocol, src)][0] += tx
        totals[(protocol, src)][1] += rx
    result = [(protocol, src, tx / frames, rx / frames) for (protocol, src), (tx, rx) in totals.items()]
    result.sort(key=lambda item: item[2] + item[3], reverse=True)
    return result, frames, len(rows)


def run_torch(host, user, interface, duration, tty):
    if not INTERFACE_RE.match(interface):
        raise SystemExit("Некоректна назва інтерфейсу: %r" % interface)
    command = ("/tool torch interface=%s src-address=0.0.0.0/0 dst-address=0.0.0.0/0 ip-protocol=any duration=%ds"
               % (interface, duration))
    ssh = ["ssh", "-o", "ConnectTimeout=10"] + (["-tt"] if tty else []) + ["%s@%s" % (user, host), command]
    try:
        # stderr і stdin лишаються підключеними до термінала, щоб ssh міг запитати пароль
        completed = subprocess.run(ssh, stdout=subprocess.PIPE, universal_newlines=True, timeout=duration + 60)
    except FileNotFoundError:
        raise SystemExit("Не знайдено команду ssh. Встановіть клієнт OpenSSH.")
    except subprocess.TimeoutExpired:
        raise SystemExit("Роутер не завершив Torch вчасно. Спробуйте ще раз або з --tty.")
    if completed.returncode != 0 and not completed.stdout.strip():
        raise SystemExit("ssh завершився з кодом %d, виводу немає." % completed.returncode)
    return completed.stdout


def print_table(result, frames, top):
    shown = result[:top]
    header = ("IP-PROTOCOL", "SRC-ADDRESS", "TX", "RX")
    lines = [(protocol, src, format_rate(tx), format_rate(rx)) for protocol, src, tx, rx in shown]
    widths = [max(len(row[i]) for row in [header] + lines) for i in range(4)]

    def line(row):
        return "%s  %s  %s  %s" % (row[0].ljust(widths[0]), row[1].ljust(widths[1]),
                                   row[2].rjust(widths[2]), row[3].rjust(widths[3]))

    print(line(header))
    for row in lines:
        print(line(row))
    total_tx = sum(item[2] for item in result)
    total_rx = sum(item[3] for item in result)
    hidden = len(result) - len(shown)
    print()
    print("Усього: TX %s, RX %s (середнє за %d кадрів Torch%s)"
          % (format_rate(total_tx), format_rate(total_rx), frames, ", ще %d рядків приховано" % hidden if hidden > 0 else ""))
    print("TX: до пристрою (завантаження), RX: від пристрою (вивантаження). Швидкості в бітах за секунду.")


def main():
    parser = argparse.ArgumentParser(description="Підсумок навантаження на мережу по пристроях (на основі /tool torch)")
    parser.add_argument("--host", default="192.168.89.1", help="адреса роутера (за замовчуванням 192.168.89.1)")
    parser.add_argument("--user", default="admin", help="користувач SSH (за замовчуванням admin)")
    parser.add_argument("--interface", default="bridge", help="інтерфейс для Torch (за замовчуванням bridge)")
    parser.add_argument("--duration", type=int, default=10, help="тривалість вимірювання, секунди (за замовчуванням 10)")
    parser.add_argument("--top", type=int, default=20, help="скільки рядків показати (за замовчуванням 20)")
    parser.add_argument("--subnet", help="показувати лише адреси з цієї підмережі, наприклад 192.168.89.0/24")
    parser.add_argument("--tty", action="store_true", help="запускати ssh з -tt (якщо без цього Torch нічого не виводить)")
    parser.add_argument("--raw", metavar="ФАЙЛ", help="зберегти сирий вивід Torch у файл")
    parser.add_argument("--input", metavar="ФАЙЛ", help="не підключатися до роутера, а розібрати збережений вивід")
    args = parser.parse_args()

    if args.duration < 1 or args.duration > 300:
        parser.error("--duration має бути від 1 до 300 секунд")
    if args.top < 1:
        parser.error("--top має бути не менше 1")
    subnet = None
    if args.subnet:
        try:
            subnet = ipaddress.IPv4Network(args.subnet, strict=False)
        except ValueError:
            parser.error("некоректна підмережа: %r" % args.subnet)

    if args.input:
        with open(args.input, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    else:
        print("Вимірюю трафік %d с на %s (інтерфейс %s)..." % (args.duration, args.host, args.interface), file=sys.stderr)
        text = run_torch(args.host, args.user, args.interface, args.duration, args.tty)
    if args.raw:
        with open(args.raw, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("Сирий вивід збережено в %s" % args.raw, file=sys.stderr)

    result, frames, parsed_lines = summarize(text, subnet)
    if parsed_lines == 0:
        print("Не вдалося розібрати жодного рядка Torch (отримано %d символів)." % len(text), file=sys.stderr)
        print("Спробуйте --tty, а для діагностики --raw файл і перегляньте його вміст.", file=sys.stderr)
        return 1
    if not result:
        print("Torch повернув %d рядків, але жоден не належить підмережі %s." % (parsed_lines, subnet), file=sys.stderr)
        return 1
    print_table(result, frames, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
