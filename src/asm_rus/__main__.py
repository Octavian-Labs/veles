"""Точка входа CLI: python -m asm_rus вход.асм [-o выход] [--цель ...]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .assembler import assemble
from .errors import AsmError


def main(argv: list[str] | None = None) -> int:
    """Разбирает аргументы командной строки и запускает ассемблер."""
    p = argparse.ArgumentParser(
        prog="rasm",
        description="РАСМ — русский ассемблер x86-64 (PE64/ELF64)",
    )
    p.add_argument("вход", help="файл исходника (.асм)")
    p.add_argument("-o", "--выход", help="имя выходного файла")
    p.add_argument(
        "--цель",
        choices=["windows", "linux"],
        default="windows" if sys.platform == "win32" else "linux",
        help="целевая платформа (по умолчанию — текущая ОС)",
    )
    args = p.parse_args(argv)

    src_path = Path(getattr(args, "вход"))
    if not src_path.is_file():
        print(f"ошибка: файл {src_path} не найден", file=sys.stderr)
        return 1
    source = src_path.read_text(encoding="utf-8")
    target = getattr(args, "цель")
    try:
        data = assemble(source, target)
    except AsmError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    out_arg = getattr(args, "выход")
    if out_arg:
        out_path = Path(out_arg)
    else:
        suffix = ".exe" if target == "windows" else ""
        out_path = (
            src_path.with_suffix(suffix)
            if suffix
            else src_path.with_name(src_path.name + ".elf")
        )
    out_path.write_bytes(data)
    print(f"собрано: {out_path} ({len(data)} байт, цель: {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
