#!/usr/bin/env python3
"""Генерує нові випадкові значення Wi-Fi і записує їх у .env.

- WIFI_PASSWORD стає випадковим паролем (за замовчуванням 16 символів);
- останні 4 символи WIFI_SSID замінюються випадковим 4-значним шістнадцятковим числом у верхньому регістрі,
  як у назвах мереж TP-Link (Tp-Link_0000 -> Tp-Link_7D15);
- з параметром --admin-password також генерується новий ADMIN_PASSWORD;
- параметр --password-length задає довжину паролів (від 8 до 63, за замовчуванням 16). Верхня межа 63 —
  обмеження WPA2/WPA3-PSK на довжину пароля Wi-Fi, вона діє і для пароля admin.

Кожен згенерований пароль містить щонайменше одну цифру, одну малу й одну велику літеру та один спецсимвол.

Решта .env (коментарі, інші параметри) лишається без змін.
Після цього запустіть generate.py, щоб оновити файли налаштувань.

Використання: python3 randomize.py [--admin-password] [--password-length N] [--env .env] [--dry-run]
Залежностей немає, потрібен лише Python 3.
"""
import argparse
import os
import random
import re
import secrets
import string
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINE_RE = re.compile(r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<eq>\s*=\s*)(?P<value>.*?)(?P<tail>\s*)$")
SSID_SUFFIX_LEN = 4
DEFAULT_PASSWORD_LENGTH = 16
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 63  # довжина парольної фрази WPA2/WPA3-PSK не може перевищувати 63 символи
# Спецсимволи підібрані так, щоб не ламати .env, рядки RouterOS ("..." з $, ?, \) і копіювання в термінал
SPECIAL_CHARS = "!@%^&*-_+=.,:~"
PASSWORD_CLASSES = (string.digits, string.ascii_lowercase, string.ascii_uppercase, SPECIAL_CHARS)
_system_random = random.SystemRandom()  # джерело випадковості ОС, як і secrets


class ConfigError(Exception):
    pass


def random_password(length):
    """Випадковий пароль заданої довжини: щонайменше по одному символу з кожного класу
    (цифра, мала літера, велика літера, спецсимвол), решта з усіх класів, порядок перемішано."""
    if length < len(PASSWORD_CLASSES):
        raise ValueError("пароль має бути не коротшим за %d символи" % len(PASSWORD_CLASSES))
    alphabet = "".join(PASSWORD_CLASSES)
    chars = [secrets.choice(group) for group in PASSWORD_CLASSES]
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    _system_random.shuffle(chars)
    return "".join(chars)


def password_length(value):
    """Тип параметра --password-length для argparse: ціле число від 8 до 63."""
    try:
        length = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("%r не є цілим числом" % value)
    if not MIN_PASSWORD_LENGTH <= length <= MAX_PASSWORD_LENGTH:
        raise argparse.ArgumentTypeError("довжина має бути від %d до %d, зараз: %d" % (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH, length))
    return length


def random_hex(length):
    """Випадкове шістнадцяткове число (0-9, A-F у верхньому регістрі) довжиною рівно length символів."""
    return "".join(secrets.choice("0123456789ABCDEF") for _ in range(length))


def unquote(value):
    """Повертає (значення без лапок, символ лапок або порожній рядок)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1], value[0]
    return value, ""


def update_env(text, new_password, new_suffix, new_admin_password=None):
    """Повертає (новий текст, старий SSID, новий SSID).

    Змінює лише рядки WIFI_PASSWORD і WIFI_SSID, а якщо задано new_admin_password, то й ADMIN_PASSWORD.
    Відсутні WIFI_PASSWORD та ADMIN_PASSWORD дописуються в кінець файлу.
    """
    lines = text.splitlines()
    new_values = {"WIFI_PASSWORD": new_password}
    if new_admin_password is not None:
        new_values["ADMIN_PASSWORD"] = new_admin_password
    seen = set()
    ssid_old = ssid_new = None

    for index, line in enumerate(lines):
        match = LINE_RE.match(line)
        if not match or line.lstrip().startswith("#"):
            continue
        key = match.group("key")
        if key not in new_values and key != "WIFI_SSID":
            continue
        value, quote = unquote(match.group("value"))
        if key in new_values:
            replacement = new_values[key]
            seen.add(key)
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
    for key, value in new_values.items():
        if key not in seen:
            lines.append("%s=%s" % (key, value))

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
    parser.add_argument("--admin-password", action="store_true",
                        help="також згенерувати новий випадковий ADMIN_PASSWORD")
    parser.add_argument("--password-length", type=password_length, default=DEFAULT_PASSWORD_LENGTH, metavar="N",
                        help="довжина згенерованих паролів, від %d до %d (за замовчуванням %d)"
                             % (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH, DEFAULT_PASSWORD_LENGTH))
    parser.add_argument("--env", default=str(ROOT / ".env"), help="шлях до файлу .env (за замовчуванням .env біля скрипта)")
    parser.add_argument("--dry-run", action="store_true", help="показати нові значення, не змінюючи файл")
    args = parser.parse_args()

    path = Path(args.env)
    try:
        if not path.is_file():
            raise ConfigError("Файл %s не знайдено. Створіть його: cp .env.example .env" % path)
        password = random_password(args.password_length)
        suffix = random_hex(SSID_SUFFIX_LEN)
        admin_password = random_password(args.password_length) if args.admin_password else None
        text, old_ssid, new_ssid = update_env(path.read_text(encoding="utf-8"), password, suffix, admin_password)
    except ConfigError as error:
        print("Помилка: %s" % error, file=sys.stderr)
        return 1

    if not args.dry_run:
        write_atomically(path, text)
    print("WIFI_SSID:      %s -> %s" % (old_ssid, new_ssid))
    print("WIFI_PASSWORD:  %s" % password)
    if admin_password is not None:
        print("ADMIN_PASSWORD: %s" % admin_password)
    if args.dry_run:
        print("(пробний запуск, %s не змінено)" % path)
    else:
        print("Записано в %s. Тепер запустіть: python3 generate.py" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
