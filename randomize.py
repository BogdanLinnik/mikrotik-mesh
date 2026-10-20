#!/usr/bin/env python3
"""Генерує нові випадкові значення Wi-Fi і записує їх у .env.

- WIFI_PASSWORD стає випадковим 16-значним числом;
- останні 4 символи WIFI_SSID замінюються випадковим 4-значним числом (Tp-Link_AD98 -> Tp-Link_0417).

Решта .env (коментарі, інші параметри) лишається без змін.
Після цього запустіть generate.py, щоб оновити файли налаштувань.

Використання: python3 randomize.py [--env .env] [--dry-run]
Залежностей немає, потрібен лише Python 3.
"""
import argparse
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINE_RE = re.compile(r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<eq>\s*=\s*)(?P<value>.*?)(?P<tail>\s*)$")
SSID_SUFFIX_LEN = 4


class ConfigError(Exception):
    pass


def random_digits(length):
    """Випадкове число з нулями попереду, довжиною рівно length цифр (криптографічно стійкий генератор)."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def unquote(value):
    """Повертає (значення без лапок, символ лапок або порожній рядок)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1], value[0]
    return value, ""


def update_env(text, new_password, new_suffix):
    """Повертає (новий текст, старий SSID, новий SSID). Змінює лише рядки WIFI_PASSWORD і WIFI_SSID."""
    lines = text.splitlines()
    password_seen = False
    ssid_old = ssid_new = None

    for index, line in enumerate(lines):
        match = LINE_RE.match(line)
        if not match or line.lstrip().startswith("#"):
            continue
        key = match.group("key")
        if key not in ("WIFI_PASSWORD", "WIFI_SSID"):
            continue
        value, quote = unquote(match.group("value"))
        if key == "WIFI_PASSWORD":
            replacement = new_password
            password_seen = True
        else:
            if len(value) <= SSID_SUFFIX_LEN:
                raise ConfigError("WIFI_SSID замалий: потрібен префікс і ще %d символи для заміни (наприклад Tp-Link_0000)" % SSID_SUFFIX_LEN)
            ssid_old = value
            ssid_new = value[:-SSID_SUFFIX_LEN] + new_suffix
            replacement = ssid_new
        lines[index] = "%s%s%s%s%s%s%s" % (
            match.group("prefix"), key, match.group("eq"), quote, replacement, quote, match.group("tail"))

    if ssid_old is None:
        raise ConfigError("У .env немає рядка WIFI_SSID=...: задайте його, наприклад WIFI_SSID=Tp-Link_0000")
    if not password_seen:
        lines.append("WIFI_PASSWORD=%s" % new_password)

    return "\n".join(lines) + "\n", ssid_old, ssid_new


def write_atomically(path, text):
    """Записує файл через тимчасовий, щоб обрив посередині не залишив пошкоджений .env."""
    mode = path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp_name, mode)
        os.replace(temp_name, str(path))
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


def main():
    parser = argparse.ArgumentParser(description="Генерує випадковий пароль Wi-Fi і суфікс SSID та записує їх у .env")
    parser.add_argument("--env", default=str(ROOT / ".env"), help="шлях до файлу .env (за замовчуванням .env біля скрипта)")
    parser.add_argument("--dry-run", action="store_true", help="показати нові значення, не змінюючи файл")
    args = parser.parse_args()

    path = Path(args.env)
    try:
        if not path.is_file():
            raise ConfigError("Файл %s не знайдено. Створіть його: cp .env.example .env" % path)
        password = random_digits(16)
        suffix = random_digits(SSID_SUFFIX_LEN)
        text, old_ssid, new_ssid = update_env(path.read_text(encoding="utf-8"), password, suffix)
    except ConfigError as error:
        print("Помилка: %s" % error, file=sys.stderr)
        return 1

    if not args.dry_run:
        write_atomically(path, text)
    print("WIFI_SSID:     %s -> %s" % (old_ssid, new_ssid))
    print("WIFI_PASSWORD: %s" % password)
    if args.dry_run:
        print("(пробний запуск, %s не змінено)" % path)
    else:
        print("Записано в %s. Тепер запустіть: python3 generate.py" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
