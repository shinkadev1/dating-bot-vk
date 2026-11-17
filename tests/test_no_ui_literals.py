"""Пользовательских литералов в коде нет: тексты, кнопки и подписи живут только во flow/flow.yaml.

Кириллица в строках app/*.py разрешена только:
- в docstring;
- в аргументах logger.* / logging.* / print;
- внутри raise;
- в re.compile / re.match / re.search и подобных;
- в ALLOWLIST ниже: маркеры протокола API с причиной.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
CYRILLIC = re.compile("[А-Яа-яЁё]")
LOG_ROOTS = {"logger", "logging", "log"}
RE_FUNCS = {"compile", "match", "search", "fullmatch", "sub", "findall"}

# (файл, литерал целиком): причина. Сюда нельзя добавлять тексты для пользователя.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("api_client.py", "премиум"): "маркер 403 в ответе Chat API: по нему отличают нехватку премиума",
    ("api_client.py", "собеседник"): "маркер ответа Chat API: премиума нет у собеседника",
    ("communities.py", "Ключ не подошёл: {msg} (код {code})"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "Нет доступа к Long Poll: {msg} (код {code})"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "{msg} (код {code})"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "Long Poll остановился: {msg} (код {code})"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "Long Poll остановился: {msg}"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "Long Poll остановился"): "служебный статус для CRM, не текст для пользователей ВК",
    ("communities.py", "Ещё не запущено"): "служебный статус для CRM, не текст для пользователей ВК",
    ("media.py", "видеосообщен"): "маркер заголовка видео в ответе VK: так узнаётся кружок",
}


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_exempt_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if isinstance(func, ast.Attribute):
        root = _root_name(func)
        if root in LOG_ROOTS:
            return True
        return root == "re" and func.attr in RE_FUNCS
    return False


def _is_docstring(node: ast.Constant, parent: ast.AST | None, grandparent: ast.AST | None) -> bool:
    return (
        isinstance(parent, ast.Expr)
        and isinstance(grandparent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and grandparent.body[0] is parent
    )


def find_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and CYRILLIC.search(node.value)):
            continue
        if _is_docstring(node, parents.get(node), parents.get(parents.get(node))):
            continue
        if (path.name, node.value) in ALLOWLIST:
            continue
        ancestor = parents.get(node)
        exempt = False
        while ancestor is not None:
            if isinstance(ancestor, ast.Raise) or (isinstance(ancestor, ast.Call) and _is_exempt_call(ancestor)):
                exempt = True
                break
            ancestor = parents.get(ancestor)
        if not exempt:
            found.append((node.lineno, node.value))
    return found


class NoUiLiteralsTests(unittest.TestCase):
    def test_no_cyrillic_ui_literals_in_code(self) -> None:
        problems = []
        for path in sorted(APP.glob("*.py")):
            for line, value in find_literals(path):
                problems.append(f"{path.name}:{line}: {value[:60]!r}")
        self.assertEqual(problems, [], "Пользовательский текст нужно перенести во flow/flow.yaml")

    def test_allowlist_entries_are_used(self) -> None:
        """Запись в ALLOWLIST без литерала в коде — мусор, её нужно убрать."""
        for (name, literal), reason in ALLOWLIST.items():
            self.assertTrue(reason)
            source = (APP / name).read_text(encoding="utf-8")
            self.assertIn(literal, source, f"{name}: {literal!r}")

    def test_detector_catches_literals(self) -> None:
        import tempfile

        sample = (
            '"""Док."""\n'
            "import logging\n"
            "logger = logging.getLogger('x')\n"
            "def f(x):\n"
            '    """Строка в docstring."""\n'
            '    logger.info("лог")\n'
            '    print("печать")\n'
            '    raise SystemExit("ошибка")\n'
            "def g():\n"
            '    a = "кнопка"\n'
            '    b = f"тест {a}"\n'
            "    return a, b\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text(sample, encoding="utf-8")
            values = sorted(v for _, v in find_literals(path))
        self.assertEqual(values, ["кнопка", "тест "])


if __name__ == "__main__":
    unittest.main()
