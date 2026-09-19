"""Выражения ассемблера: числа, метки, арифметика, текущий адрес ($).

Выражения представлены деревьями и вычисляются на втором проходе,
когда адреса всех меток уже известны.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AsmError


class Expr:
    """Базовый класс узла выражения."""


@dataclass
class Num(Expr):
    """Целочисленный литерал."""

    value: int


@dataclass
class Sym(Expr):
    """Символическое имя (метка или константа)."""

    name: str


@dataclass
class Here(Expr):
    """Текущий адрес ($ или ЗДЕСЬ)."""


@dataclass
class Bin(Expr):
    """Бинарная операция над двумя выражениями."""

    op: str
    left: Expr
    right: Expr


@dataclass
class Neg(Expr):
    """Унарный минус."""

    x: Expr


@dataclass
class Not(Expr):
    """Побитовое НЕ (~)."""

    x: Expr


_BINOPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a // b,
    "%": lambda a, b: a % b,
    "<<": lambda a, b: a << b,
    ">>": lambda a, b: a >> b,
    "&": lambda a, b: a & b,
    "|": lambda a, b: a | b,
    "^": lambda a, b: a ^ b,
}


def eval_expr(e: Expr, ctx) -> int:
    """Вычисляет выражение через контекст (resolve_sym / here)."""
    if isinstance(e, Num):
        return e.value
    if isinstance(e, Sym):
        return ctx.resolve_sym(e.name)
    if isinstance(e, Here):
        return ctx.here()
    if isinstance(e, Neg):
        return -eval_expr(e.x, ctx)
    if isinstance(e, Not):
        return ~eval_expr(e.x, ctx)
    if isinstance(e, Bin):
        a = eval_expr(e.left, ctx)
        b = eval_expr(e.right, ctx)
        try:
            return _BINOPS[e.op](a, b)
        except KeyError:
            raise AsmError(f"неизвестная операция {e.op!r}")
        except ZeroDivisionError:
            raise AsmError("деление на ноль в выражении")
    raise AsmError(f"некорректное выражение: {e!r}")


def has_sym(e: Expr | None) -> bool:
    """Проверяет, содержит ли выражение символ (метку/константу/$)."""
    if e is None:
        return False
    if isinstance(e, (Sym, Here)):
        return True
    if isinstance(e, (Neg, Not)):
        return has_sym(e.x)
    if isinstance(e, Bin):
        return has_sym(e.left) or has_sym(e.right)
    return False
