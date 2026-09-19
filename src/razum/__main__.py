"""CLI компилятора РАЗУМ.

Использование:
    python -m razum файл.раз [-o выход.exe] [--цель windows|linux]
                           [--искра файл.иск]  # сохранить сгенерированный асм
                           [--только-иск]      # не вызывать ассемблер
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import RazError
from .gen import generate
from .loader import загрузить


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="razum", description="Компилятор языка РАЗУМ (ВЕЛЕС)"
    )
    p.add_argument("вход", help="исходный файл .раз")
    p.add_argument("-o", "--выход", help="выходной исполняемый файл")
    p.add_argument(
        "--цель",
        choices=["windows", "linux"],
        default="windows",
        help="целевая ОС (по умолчанию windows)",
    )
    p.add_argument("--искра", help="сохранить сгенерированный текст ИСКРЫ")
    p.add_argument(
        "--только-иск",
        action="store_true",
        help="только сгенерировать .иск, без ассемблирования",
    )
    args = p.parse_args(argv)

    src_path = Path(args.вход)
    if not src_path.exists():
        print(f"ошибка: файл {src_path} не найден", file=sys.stderr)
        return 2
    try:
        прог = загрузить(src_path, target=args.цель)
        искра = generate(прог, target=args.цель)
    except RazError as e:
        print(f"разум: {e}", file=sys.stderr)
        return 1

    if args.искра:
        Path(args.искра).write_text(искра, encoding="utf-8")
    if args.только_иск:
        if not args.искра:
            print(искра)
        return 0

    from ..iskra.assembler import assemble
    from ..iskra.errors import AsmError

    try:
        бин = assemble(искра, target=args.цель)
    except AsmError as e:
        # сгенерированный текст оставляем для отладки
        дебаг = src_path.with_suffix(".ген.иск")
        дебаг.write_text(искра, encoding="utf-8")
        print(f"искра: {e}\n(сгенерированный текст: {дебаг})", file=sys.stderr)
        return 1

    суффикс = ".exe" if args.цель == "windows" else ""
    out = Path(args.выход) if args.выход else src_path.with_suffix(суффикс)
    out.write_bytes(бин)
    print(f"собрано: {out} ({len(бин)} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
