#!/usr/bin/env python3
"""Живий список найактивніших Wi-Fi клієнтів: те саме, що `traffic.py --max-only`, але з постійним оновленням.

Скрипт одним SSH-з'єднанням до RB4011 раз на --interval секунд знімає лічильники (лише команди print) і
показує топ клієнтів за TX з колонкою точки доступу. Швидкість це різниця лічильників між двома
сусідніми зрізами, поділена на час між ними за годинником роутера. Таблиця перемальовується на місці.

TX: від точки до пристрою (завантаження на пристрій), RX: від пристрою до точки (вивантаження з пристрою).

Використання:
    python3 live.py [--host 192.168.89.1] [--user admin] [--interval 5] [--top 10] [--source ax3-1]
Вихід: Ctrl+C. Пароль SSH запитує сам ssh один раз, далі з'єднання використовується повторно.
Залежностей немає, потрібен лише Python 3 і ssh.
"""
import argparse
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import traffic

TIMESTAMP_RE = re.compile(r"^(?:(\d+)w)?(?:(\d+)d)?(\d+):(\d+):(\d+)(?:\.(\d+))?$")
COMMAND = (
    ':put "###ts"; :put [:timestamp]; '
    ':put "###static_caps"; /interface wifi capsman remote-cap print terse without-paging; '
    ':put "###static_hosts"; /interface bridge host print terse without-paging where !local; '
    ':put "###static_leases"; /ip dhcp-server lease print terse without-paging; '
    ':put "###reg"; /interface wifi registration-table print stats without-paging; '
    ':put "###if"; /interface print stats-detail without-paging; '
    ':put "###end"'
)


def parse_timestamp(lines):
    """Час роутера (`:timestamp`, наприклад 20747w3d09:30:11.123456) у секундах; None, якщо формат невідомий."""
    for line in lines:
        match = TIMESTAMP_RE.match(line.strip())
        if match:
            weeks, days, hours, minutes, seconds, fraction = match.groups()
            total = int(weeks or 0) * 604800 + int(days or 0) * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            return total + (float("0." + fraction) if fraction else 0.0)
    return None


class Router:
    """Одне SSH-з'єднання (ControlMaster), яке використовується для всіх запитів."""

    def __init__(self, host, user):
        self.target = "%s@%s" % (user, host)
        # Шлях сокета має бути коротким (ліміт ОС ~100 байт), тому окремий короткий каталог
        self.directory = tempfile.mkdtemp(prefix="rb")
        self.options = ["-o", "ConnectTimeout=10", "-o", "ControlMaster=auto",
                        "-o", "ControlPath=" + os.path.join(self.directory, "s"), "-o", "ControlPersist=60"]

    def connect(self):
        """Перший запит йде з підключеним терміналом, щоб ssh міг запитати пароль."""
        try:
            completed = subprocess.run(["ssh"] + self.options + [self.target, ":put ok"], stdout=subprocess.PIPE,
                                       universal_newlines=True, timeout=120)
        except FileNotFoundError:
            raise SystemExit("Не знайдено команду ssh. Встановіть клієнт OpenSSH.")
        if completed.returncode != 0:
            raise SystemExit("Не вдалося підключитися до %s (ssh код %d)." % (self.target, completed.returncode))

    def poll(self):
        try:
            completed = subprocess.run(["ssh"] + self.options + [self.target, COMMAND], stdout=subprocess.PIPE,
                                       stdin=subprocess.DEVNULL, universal_newlines=True, timeout=30)
        except subprocess.TimeoutExpired:
            return None
        if completed.returncode != 0 or "###end" not in completed.stdout:
            return None
        return traffic.split_sections(completed.stdout)

    def close(self):
        subprocess.run(["ssh", "-O", "exit"] + self.options + [self.target], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        shutil.rmtree(self.directory, ignore_errors=True)


def render(aps, seconds, top, interval, source):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        traffic.print_max_only(aps, seconds, top, source)
    return buffer.getvalue() + "\nОновлення кожні %d с, %s. Вихід: Ctrl+C\n" % (interval, time.strftime("%H:%M:%S"))


def show(text, interactive):
    if interactive:
        # На початок екрана, кожен рядок дочищається до кінця, залишок екрана стирається: без мигання
        text = "\033[H" + text.replace("\n", "\033[K\n") + "\033[J"
    sys.stdout.write(text)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Живий топ Wi-Fi клієнтів за навантаженням")
    parser.add_argument("--host", default="192.168.89.1", help="адреса RB4011 (за замовчуванням 192.168.89.1)")
    parser.add_argument("--user", default="admin", help="користувач SSH (за замовчуванням admin)")
    parser.add_argument("--interval", type=int, default=5, help="пауза між оновленнями, секунди (2-60, за замовчуванням 5)")
    parser.add_argument("--top", type=int, default=10, help="скільки клієнтів показувати (за замовчуванням 10)")
    parser.add_argument("--source", metavar="ТОЧКА",
                        help="показувати лише клієнтів цієї точки (rb4011, ac3-1, ax3-2, ...), за замовчуванням усіх")
    parser.add_argument("--count", type=int, default=0, help="зупинитися після стількох оновлень (0 = без обмеження)")
    args = parser.parse_args()
    if not 2 <= args.interval <= 60:
        parser.error("--interval має бути від 2 до 60 секунд")
    if args.top < 1:
        parser.error("--top має бути не менше 1")

    interactive = sys.stdout.isatty()
    router = Router(args.host, args.user)
    previous = None
    previous_time = None
    shown = 0
    try:
        router.connect()
        if interactive:
            sys.stdout.write("\033[2J")
        print("Збираю першу вибірку...", flush=True)
        while True:
            started = time.monotonic()
            current = router.poll()
            if current is None:
                if previous is not None:
                    show("Не вдалося отримати дані з роутера, повторюю...\n", interactive)
                else:
                    raise SystemExit("Роутер не повернув дані. Перевірте адресу й пароль.")
            else:
                now = parse_timestamp(current.get("ts", []))
                if now is None:
                    now = time.monotonic()  # запасний варіант: годинник цього комп'ютера
                if previous is not None and now > previous_time:
                    sections = dict(current)
                    sections["reg1"], sections["if1"] = previous["reg"], previous["if"]
                    sections["reg2"], sections["if2"] = current["reg"], current["if"]
                    seconds = now - previous_time
                    show(render(traffic.analyze_sections(sections, seconds), round(seconds), args.top, args.interval, args.source),
                         interactive)
                    shown += 1
                    if args.count and shown >= args.count:
                        break
                previous, previous_time = current, now
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print()
    finally:
        router.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
