"""Загрузчик модулей РАЗУМА: рекурсивное разрешение «взять имя».

Порядок поиска модуля «имя» для цели target:
    <каталог источника>/имя.<target>.раз   (платформенная реализация)
    <каталог источника>/имя.раз
    <каталог источника>/lib/имя.<target>.раз
    <каталог источника>/lib/имя.раз
    <каталог источника>/../lib/...         (lib/ уровнем выше — корень проекта)

Каждый файл разбирается один раз; циклические импорты отсекаются.
"""

from __future__ import annotations

from pathlib import Path

from . import nodes as N
from .errors import RazError
from .parser import parse


def _кандидаты(имя: str, каталог: Path, target: str):
    """Пути-кандидаты: платформенный файл имеет приоритет."""
    for база in (каталог, каталог / "lib", каталог.parent / "lib"):
        yield база / f"{имя}.{target}.раз"
        yield база / f"{имя}.раз"


def _найди_модуль(имя: str, каталог: Path, target: str) -> Path:
    """Ищет файл модуля по кандидатам; бросает RazError, если не нашёл."""
    for путь in _кандидаты(имя, каталог, target):
        if путь.exists():
            return путь
    raise RazError(f"взять {имя}: модуль не найден рядом с {каталог} или в lib/", 0)


def загрузить(вход: Path, target: str = "windows") -> N.Программа:
    """Читает файл .раз и рекурсивно подключает модули «взять»."""
    seen: set[Path] = set()
    decls: list = []

    def обход(файл: Path):
        канон = файл.resolve()
        if канон in seen:
            return  # уже подключён (или цикл) — пропускаем
        seen.add(канон)
        прог = parse(файл.read_text(encoding="utf-8"))
        for d in прог.decls:
            if isinstance(d, N.Взять):
                for м in d.модули:
                    обход(_найди_модуль(м, файл.parent, target))
            else:
                decls.append(d)

    обход(вход)
    return N.Программа(decls)
