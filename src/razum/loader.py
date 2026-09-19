"""Загрузчик модулей РАЗУМА: рекурсивное разрешение «взять имя».

Модуль ищется по имени: <каталог источника>/имя.раз, затем
<каталог источника>/lib/имя.раз (там будет жить stdlib «основа»).
Каждый файл разбирается один раз; циклические импорты отсекаются.
"""

from __future__ import annotations

from pathlib import Path

from . import nodes as N
from .errors import RazError
from .parser import parse


def _найди_модуль(имя: str, каталог: Path) -> Path:
    """Ищет файл модуля рядом с импортирующим источником и в lib/."""
    for путь in (каталог / f"{имя}.раз", каталог / "lib" / f"{имя}.раз"):
        if путь.exists():
            return путь
    raise RazError(f"взять {имя}: модуль не найден рядом с {каталог} или в lib/", 0)


def загрузить(вход: Path) -> N.Программа:
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
                    обход(_найди_модуль(м, файл.parent))
            else:
                decls.append(d)

    обход(вход)
    return N.Программа(decls)
