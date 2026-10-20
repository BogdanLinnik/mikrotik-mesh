#!/usr/bin/env python3
"""Генерує .rsc файли налаштувань для всіх пристроїв зі значень у .env.

Результат кладеться в каталог generated/ (він у .gitignore, бо файли містять паролі):
rb4011.rsc, ac3-1.rsc, ac3-2.rsc, ax3-1.rsc, ax3-2.rsc, ...

Використання: python3 generate.py [--env .env] [--out generated]
Залежностей немає, потрібен лише Python 3.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"

PLACEHOLDER_PASSWORDS = {"change-me", "change-me-too"}
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


class ConfigError(Exception):
    pass


def load_env(path):
    """Читає файл формату KEY=VALUE. Лапки навколо значення знімаються, екранування всередині немає."""
    if not path.is_file():
        raise ConfigError("Файл %s не знайдено. Створіть його: cp .env.example .env" % path)
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfigError("%s:%d: очікується рядок виду KEY=VALUE" % (path, number))
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def routeros_escape(value):
    """Екранує рядок для використання всередині "..." у скриптах RouterOS.

    Символи \\, ", $ та ? мають спеціальне значення, тому перед ними ставиться зворотна скісна риска.
    """
    for char in ("\\", '"', "$", "?"):
        value = value.replace(char, "\\" + char)
    return value


def parse_count(env, key, errors):
    raw = env.get(key, "2")
    try:
        count = int(raw)
    except ValueError:
        errors.append("%s має бути цілим числом, зараз: %r" % (key, raw))
        return 0
    if count < 0 or count > 20:
        errors.append("%s має бути від 0 до 20, зараз: %d" % (key, count))
        return 0
    return count


def validate(env):
    """Перевіряє значення з .env і повертає налаштування для підстановки в шаблони."""
    errors = []

    def required(key):
        value = env.get(key, "")
        if not value:
            errors.append("%s не задано в .env" % key)
        elif "\n" in value or "\r" in value:
            errors.append("%s не може містити переносів рядка" % key)
        return value

    admin_password = required("ADMIN_PASSWORD")
    wifi_password = required("WIFI_PASSWORD")
    ssid = required("WIFI_SSID")
    country = env.get("WIFI_COUNTRY", "") or "Ukraine"

    if admin_password in PLACEHOLDER_PASSWORDS:
        errors.append("ADMIN_PASSWORD містить значення-приклад з .env.example, задайте свій пароль")
    if wifi_password in PLACEHOLDER_PASSWORDS:
        errors.append("WIFI_PASSWORD містить значення-приклад з .env.example, задайте свій пароль")
    if wifi_password and not 8 <= len(wifi_password) <= 63:
        errors.append("WIFI_PASSWORD має бути від 8 до 63 символів, зараз: %d" % len(wifi_password))
    # SSID не довший за 32 байти разом із суфіксом -5g
    if ssid and len((ssid + "-5g").encode("utf-8")) > 32:
        errors.append("WIFI_SSID задовгий: SSID для 5 ГГц (з суфіксом -5g) має вміщатися в 32 байти")

    ac3_count = parse_count(env, "AC3_COUNT", errors)
    ax3_count = parse_count(env, "AX3_COUNT", errors)

    if errors:
        raise ConfigError("\n".join("  - " + message for message in errors))

    return {
        "ADMIN_PASSWORD": routeros_escape(admin_password),
        "WIFI_PASSWORD": routeros_escape(wifi_password),
        "SSID_2G": routeros_escape(ssid),
        "SSID_5G": routeros_escape(ssid + "-5g"),
        "COUNTRY": routeros_escape(country),
        "AC3_COUNT": ac3_count,
        "AX3_COUNT": ax3_count,
    }


def render(template_name, values):
    text = (TEMPLATES / template_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, str(value))
    leftover = sorted(set(PLACEHOLDER_RE.findall(text)))
    if leftover:
        raise ConfigError("У шаблоні %s лишилися непідставлені параметри: %s" % (template_name, ", ".join(leftover)))
    return text


def devices(config):
    """Повертає список (ім'я файлу, шаблон, параметри). Імена пристроїв унікальні в межах мережі."""
    common = {key: config[key] for key in ("ADMIN_PASSWORD", "WIFI_PASSWORD", "SSID_2G", "SSID_5G", "COUNTRY")}
    result = [("rb4011", "rb4011.rsc.tpl", dict(common, IDENTITY="rb4011"))]
    for index in range(1, config["AC3_COUNT"] + 1):
        identity = "ac3-%d" % index
        result.append((identity, "cap.rsc.tpl", dict(common, IDENTITY=identity, MODEL="hAP ac3", WIFI_PACKAGE="wifi-qcom-ac")))
    for index in range(1, config["AX3_COUNT"] + 1):
        identity = "ax3-%d" % index
        result.append((identity, "cap.rsc.tpl", dict(common, IDENTITY=identity, MODEL="hAP ax3", WIFI_PACKAGE="wifi-qcom")))
    return result


def main():
    parser = argparse.ArgumentParser(description="Генерує .rsc файли налаштувань зі значень у .env")
    parser.add_argument("--env", default=str(ROOT / ".env"), help="шлях до файлу .env (за замовчуванням .env біля скрипта)")
    parser.add_argument("--out", default=str(ROOT / "generated"), help="каталог для результату (за замовчуванням generated/)")
    args = parser.parse_args()

    try:
        config = validate(load_env(Path(args.env)))
        rendered = [(name, render(template, values)) for name, template, values in devices(config)]
    except ConfigError as error:
        print("Помилка:\n%s" % error, file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Видаляємо старі .rsc, щоб після зміни кількості пристроїв не лишалися зайві файли
    for old in out_dir.glob("*.rsc"):
        old.unlink()
    for name, text in rendered:
        path = out_dir / (name + ".rsc")
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)  # у файлах паролі
        print("Створено %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
