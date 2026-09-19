"""Парсер ИСКРЫ: токены -> операторы (инструкции, директивы, метки).

Грамматика строки:
    [метка:] [МНЕМОНИКА оп1, оп2, ...] [; комментарий]
    [метка:] ДИРЕКТИВА аргументы
    имя РАВНО выражение
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import AsmError
from .expr import Bin, Expr, Here, Neg, Not, Num, Sym
from .lexer import Tok, tokenize
from .regs import lookup as reg_lookup

# --- Операнды ---------------------------------------------------------------


@dataclass
class Reg:
    """Регистровый операнд."""

    num: int
    size: int  # байт: 1, 2, 4, 8
    need_rex: bool = False


@dataclass
class Imm:
    """Непосредственный операнд (число, метка, выражение)."""

    expr: Expr


@dataclass
class Mem:
    """Адресный операнд [база + индекс*масштаб + смещение]."""

    base: Reg | None = None
    index: Reg | None = None
    scale: int = 1
    disp: Expr | None = None
    size: int | None = None  # явный размер: БАЙТ/СЛОВО/ДВСЛОВО/КВАД


# --- Операторы --------------------------------------------------------------


@dataclass
class Instr:
    """Машинная инструкция."""

    mnem: str
    ops: list = field(default_factory=list)
    line: int = 0


@dataclass
class Dir:
    """Директива ассемблера (СЕКЦИЯ, БАЙТ, ИМПОРТ и т.д.)."""

    name: str
    args: list = field(default_factory=list)
    line: int = 0


@dataclass
class Label:
    """Метка."""

    name: str
    line: int = 0


@dataclass
class Equ:
    """Константа: имя РАВНО выражение."""

    name: str
    expr: Expr = None
    line: int = 0


# РАВНО здесь нет: оно разбирается отдельно как «имя РАВНО выражение»,
# а в позиции мнемоники это условный переход (je).
DIRECTIVES = {
    "СЕКЦИЯ",
    "БАЙТ",
    "СЛОВО",
    "ДВСЛОВО",
    "КВАД",
    "ВЫРОВНЯТЬ",
    "РЕЗЕРВ",
    "ИМПОРТ",
    "ВХОД",
}

_SIZE_WORDS = {"БАЙТ": 1, "СЛОВО": 2, "ДВСЛОВО": 4, "КВАД": 8}


class _Stream:
    """Курсор по токенам одной строки."""

    def __init__(self, toks: list[Tok], line: int):
        self.toks = toks
        self.i = 0
        self.line = line

    def peek(self) -> Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> Tok | None:
        t = self.peek()
        if t is not None:
            self.i += 1
        return t

    def expect_punct(self, ch: str) -> Tok:
        t = self.next()
        if t is None or t.kind != "punct" or t.val != ch:
            raise AsmError(f"ожидался символ {ch!r}", self.line)
        return t

    def at_end(self) -> bool:
        return self.i >= len(self.toks)


# --- Выражения --------------------------------------------------------------


def _parse_expr(st: _Stream) -> Expr:
    """Разбирает выражение с приоритетами операций."""
    return _parse_or(st)


def _binary(st: _Stream, ops: set[str], sub) -> Expr:
    """Общий разбор левоассоциативных бинарных операций."""
    left = sub(st)
    while True:
        t = st.peek()
        if t is not None and t.kind == "punct" and t.val in ops:
            st.next()
            left = Bin(t.val, left, sub(st))
        else:
            return left


def _parse_or(st: _Stream) -> Expr:
    return _binary(st, {"|"}, _parse_xor)


def _parse_xor(st: _Stream) -> Expr:
    return _binary(st, {"^"}, _parse_and)


def _parse_and(st: _Stream) -> Expr:
    return _binary(st, {"&"}, _parse_shift)


def _parse_shift(st: _Stream) -> Expr:
    return _binary(st, {"<<", ">>"}, _parse_add)


def _parse_add(st: _Stream) -> Expr:
    return _binary(st, {"+", "-"}, _parse_mul)


def _parse_mul(st: _Stream) -> Expr:
    return _binary(st, {"*", "/", "%"}, _parse_unary)


def _parse_unary(st: _Stream) -> Expr:
    t = st.peek()
    if t is not None and t.kind == "punct":
        if t.val == "-":
            st.next()
            return Neg(_parse_unary(st))
        if t.val == "~":
            st.next()
            return Not(_parse_unary(st))
        if t.val == "+":
            st.next()
            return _parse_unary(st)
    return _parse_atom(st)


def _parse_atom(st: _Stream) -> Expr:
    t = st.next()
    if t is None:
        raise AsmError("неожиданный конец выражения", st.line)
    if t.kind == "num":
        return Num(t.val)
    if t.kind == "id":
        if t.val.upper() == "ЗДЕСЬ":
            return Here()
        return Sym(t.val)
    if t.kind == "str" and len(t.val) == 1:
        return Num(ord(t.val))
    if t.kind == "punct":
        if t.val == "$":
            return Here()
        if t.val == "(":
            e = _parse_expr(st)
            st.expect_punct(")")
            return e
    raise AsmError(f"неожиданный токен {t.val!r} в выражении", st.line)


# --- Операнды ---------------------------------------------------------------


def _split_terms(st: _Stream) -> list[tuple[int, list[Tok]]]:
    """Делит содержимое скобок [...] на слагаемые по + и - верхнего уровня.

    Возвращает список (знак, токены_слагаемого).
    """
    terms: list[tuple[int, list[Tok]]] = []
    sign = 1
    cur: list[Tok] = []
    depth = 0
    while True:
        t = st.peek()
        if t is None:
            break
        if t.kind == "punct" and t.val == "]" and depth == 0:
            break
        st.next()
        if t.kind == "punct" and t.val == "(":
            depth += 1
        elif t.kind == "punct" and t.val == ")":
            depth -= 1
        if t.kind == "punct" and t.val in "+-" and depth == 0:
            terms.append((sign, cur))
            cur = []
            sign = 1 if t.val == "+" else -1
        else:
            cur.append(t)
    terms.append((sign, cur))
    return terms


def _parse_mem(st: _Stream, size: int | None) -> Mem:
    """Разбирает адресный операнд после '['."""
    mem = Mem(size=size)
    disp_terms: list[tuple[int, list[Tok]]] = []
    for sign, toks in _split_terms(st):
        # слагаемое вида РЕГ, РЕГ*N или N*РЕГ — регистровое
        reg: Reg | None = None
        scale = 1
        rest = toks
        if len(toks) >= 1 and toks[0].kind == "id":
            info = reg_lookup(str(toks[0].val))
            if info is not None:
                reg = Reg(*info)
                rest = toks[1:]
                if (
                    len(rest) == 2
                    and rest[0].kind == "punct"
                    and rest[0].val == "*"
                    and rest[1].kind == "num"
                ):
                    scale = int(rest[1].val)
                    rest = []
                elif len(rest) == 0:
                    scale = 1
        if (
            reg is None
            and len(toks) == 3
            and toks[0].kind == "num"
            and toks[1].kind == "punct"
            and toks[1].val == "*"
            and toks[2].kind == "id"
            and reg_lookup(str(toks[2].val)) is not None
        ):
            info = reg_lookup(str(toks[2].val))
            reg = Reg(*info)
            scale = int(toks[0].val)
            rest = []
        if reg is not None and not rest:
            if scale != 1 or mem.base is not None:
                if mem.index is not None:
                    raise AsmError("лишний индексный регистр в адресе", st.line)
                mem.index = reg
                mem.scale = scale
            else:
                mem.base = reg
            if sign < 0:
                raise AsmError("регистр в адресе нельзя вычитать", st.line)
        else:
            disp_terms.append((sign, toks))
    st.expect_punct("]")
    if disp_terms:
        expr: Expr | None = None
        for sign, toks in disp_terms:
            sub = _Stream(toks, st.line)
            part = _parse_expr(sub)
            if not sub.at_end():
                raise AsmError("лишние токены в смещении адреса", st.line)
            part = part if sign > 0 else Neg(part)
            expr = part if expr is None else Bin("+", expr, part)
        mem.disp = expr
    if mem.base is None and mem.index is None and mem.disp is None:
        raise AsmError("пустой адресный операнд []", st.line)
    return mem


def _parse_operand(st: _Stream):
    """Разбирает один операнд: регистр, [адрес], размер [адрес] или выражение."""
    t = st.peek()
    if t is not None and t.kind == "id":
        name = str(t.val).upper()
        if name in _SIZE_WORDS and st.i + 1 < len(st.toks):
            t2 = st.toks[st.i + 1]
            if t2.kind == "punct" and t2.val == "[":
                st.next()  # размер
                st.next()  # '['
                return _parse_mem(st, _SIZE_WORDS[name])
        info = reg_lookup(str(t.val))
        if info is not None:
            st.next()
            return Reg(*info)
    if t is not None and t.kind == "punct" and t.val == "[":
        st.next()
        return _parse_mem(st, None)
    return Imm(_parse_expr(st))


# --- Строки -----------------------------------------------------------------


def _is_directive(name: str) -> bool:
    return name.upper() in DIRECTIVES


def parse_line(toks: list[Tok]) -> list:
    """Разбирает одну строку токенов в список операторов."""
    out: list = []
    if not toks:
        return out
    line = toks[0].line
    st = _Stream(toks, line)
    # метка в начале строки: ИМЯ ':'
    t = st.peek()
    if (
        t is not None
        and t.kind == "id"
        and st.i + 1 < len(toks)
        and toks[st.i + 1].kind == "punct"
        and toks[st.i + 1].val == ":"
    ):
        out.append(Label(str(t.val), line))
        st.next()
        st.next()
    if st.at_end():
        return out
    t = st.next()
    if t is None or t.kind != "id":
        raise AsmError("ожидалась мнемоника или директива", line)
    name = str(t.val).upper()
    # константа: ИМЯ РАВНО выражение
    t2 = st.peek()
    if t2 is not None and t2.kind == "id" and str(t2.val).upper() == "РАВНО":
        st.next()
        out.append(Equ(str(t.val), _parse_expr(st), line))
        if not st.at_end():
            raise AsmError("лишние токены после РАВНО", line)
        return out
    # директива
    if _is_directive(name):
        out.append(_parse_directive(st, name, line))
        return out
    # обычная инструкция
    ops: list = []
    while not st.at_end():
        ops.append(_parse_operand(st))
        t3 = st.peek()
        if t3 is not None:
            if t3.kind == "punct" and t3.val == ",":
                st.next()
            else:
                raise AsmError(f"ожидалась запятая, найдено {t3.val!r}", line)
    out.append(Instr(name, ops, line))
    return out


def _parse_directive(st: _Stream, name: str, line: int) -> Dir:
    """Разбирает аргументы директивы."""
    args: list = []
    if name == "СЕКЦИЯ":
        t = st.next()
        if t is None or t.kind not in ("id", "str"):
            raise AsmError("СЕКЦИЯ: ожидалось имя секции", line)
        return Dir(name, [str(t.val)], line)
    if name == "ИМПОРТ":
        t = st.next()
        if t is None or t.kind != "str":
            raise AsmError("ИМПОРТ: ожидалось имя DLL в кавычках", line)
        args.append(t.val)
        while not st.at_end():
            t = st.next()
            if t.kind == "id":
                args.append(str(t.val))
            elif t.kind == "punct" and t.val == ",":
                continue
            else:
                raise AsmError(f"ИМПОРТ: неожиданный токен {t.val!r}", line)
        return Dir(name, args, line)
    if name in ("ВХОД", "ВЫРОВНЯТЬ", "РЕЗЕРВ"):
        args.append(_parse_expr(st))
    elif name in ("БАЙТ", "СЛОВО", "ДВСЛОВО", "КВАД"):
        while not st.at_end():
            t = st.peek()
            if t.kind == "str" and name == "БАЙТ":
                st.next()
                args.append(t.val)
            else:
                args.append(_parse_expr(st))
            t = st.peek()
            if t is not None:
                if t.kind == "punct" and t.val == ",":
                    st.next()
                else:
                    raise AsmError("ожидалась запятая в данных", line)
    else:
        raise AsmError(f"неизвестная директива {name}", line)
    if not st.at_end():
        raise AsmError(f"лишние токены в директиве {name}", line)
    return Dir(name, args, line)


def parse(source: str) -> list:
    """Разбирает весь исходник в плоский список операторов."""
    stmts: list = []
    for toks in tokenize(source):
        stmts.extend(parse_line(toks))
    return stmts
