"""Контент бота из app/content/content.json: тексты, кнопки, списки, клавиатуры и картинки.

Файл редактируется в Bot CRM, код только читает его при запуске. Ошибка в файле видна сразу
при старте (ContentError с понятным путём), а не посреди диалога.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTENT_DIR = Path(__file__).resolve().parent / "content"
CONTENT_FILE = CONTENT_DIR / "content.json"
FORMAT = "bot-crm/1"
COLORS = {"primary", "success", "danger", "secondary"}


class ContentError(RuntimeError):
    """content.json не прочитан или в нём нет нужного значения."""


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContentError(f"Нет файла контента {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContentError(f"{path.name}: ошибка JSON в строке {exc.lineno}: {exc.msg}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ContentError(f"{path.name}: ожидается format={FORMAT!r}")
    return data


_data = _load(CONTENT_FILE)


def _section(name: str) -> dict[str, Any]:
    value = _data.get(name)
    if not isinstance(value, dict):
        raise ContentError(f"content.json: нет раздела {name}")
    return value


def _string(section: str, key: str) -> str:
    value = _section(section).get(key)
    if not isinstance(value, str):
        raise ContentError(f"content.json: нет строки {section}.{key}")
    return value


def text(key: str) -> str:
    """Текст сообщения."""
    return _string("texts", key)


def button(key: str) -> str:
    """Подпись кнопки."""
    return _string("buttons", key)


def button_variants(key: str) -> set[str]:
    """Подпись кнопки и её прежние подписи (button_aliases) в нижнем регистре.

    У людей может остаться старая клавиатура: нажатие пришлёт прежний текст.
    Bot CRM дописывает старую подпись в button_aliases при переименовании кнопки.
    """
    aliases = _data.get("button_aliases", {}).get(key, [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ContentError(f"content.json: button_aliases.{key} должен быть списком строк")
    return {button(key).strip().lower(), *(a.strip().lower() for a in aliases)}


def items(name: str) -> dict[str, str]:
    """Список «ключ → подпись» (города, тарифы…). Порядок как в файле."""
    value = _section("lists").get(name, {}).get("items")
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ContentError(f"content.json: нет списка lists.{name}.items")
    return dict(value)


def keyboard(name: str) -> dict[str, Any]:
    """Клавиатура: type (reply/inline) и rows — ряды ячеек {button|list+item, color}."""
    kb = _section("keyboards").get(name)
    if not isinstance(kb, dict) or not isinstance(kb.get("rows"), list):
        raise ContentError(f"content.json: нет клавиатуры keyboards.{name}")
    for row in kb["rows"]:
        for cell in row:
            label(cell)  # проверяем ссылки сразу при запуске
            if cell.get("color") not in (None, *COLORS):
                raise ContentError(f"keyboards.{name}: неизвестный цвет {cell.get('color')!r}")
    return kb


def label(cell: dict[str, Any]) -> str:
    """Подпись ячейки клавиатуры."""
    if "button" in cell:
        return button(cell["button"])
    if "list" in cell:
        values = items(cell["list"])
        if cell.get("item") not in values:
            raise ContentError(f"content.json: нет элемента {cell.get('item')!r} в lists.{cell['list']}")
        return values[cell["item"]]
    raise ContentError(f"content.json: у кнопки нет button или list: {cell}")


def image_path(name: str) -> Path:
    """Путь к картинке из раздела images."""
    entry = _section("images").get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        raise ContentError(f"content.json: нет картинки images.{name}")
    path = (CONTENT_DIR / entry["file"]).resolve()
    if CONTENT_DIR not in path.parents:
        raise ContentError(f"images.{name}: файл должен лежать внутри app/content")
    return path
