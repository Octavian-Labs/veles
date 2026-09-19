"""Двухпроходный ассемблер РАСМ.

Проход 1: размеры инструкций и смещения меток внутри секций.
Планировка: эмиттер назначает адреса секций и ячеек IAT.
Проход 2: окончательное кодирование с реальными адресами.
Сборка: эмиттер формирует исполняемый файл (PE64 или ELF64).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .encoder import encode
from .errors import AsmError
from .expr import Sym, eval_expr
from .parser import Dir, Equ, Instr, Label, parse

SECTIONS = {
    "код": "код",
    "text": "код",
    "code": "код",
    ".text": "код",
    ".код": "код",
    "данные": "данные",
    "data": "данные",
    ".data": "данные",
    ".данные": "данные",
}

_DATA_SIZES = {"БАЙТ": 1, "СЛОВО": 2, "ДВСЛОВО": 4, "КВАД": 8}


@dataclass
class _Placed:
    """Оператор, привязанный к секции и смещению."""

    stmt: object
    section: str
    offset: int
    size: int


@dataclass
class _Program:
    """Результат разбора и первого прохода."""

    placed: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # имя -> (секция, смещение)
    consts: dict = field(default_factory=dict)  # имя -> (выражение, секция, смещение)
    imports: list = field(default_factory=list)  # [(dll, [функции])]
    entry: str | None = None
    sizes: dict = field(default_factory=dict)  # секция -> размер


class _DryCtx:
    """Контекст первого прохода: адреса ещё не назначены, даём нули.

    Длина инструкции зависит только от видов операндов, поэтому
    нулевые значения меток не влияют на вычисляемый размер.
    Список импортов нужен уже здесь: «ВЫЗОВ импорта» и «ВЫЗОВ метки»
    имеют разную длину (6 и 5 байт).
    """

    va = 0

    def __init__(self, imports: set):
        self._imports = imports

    def resolve_sym(self, name: str) -> int:
        return 0

    def here(self) -> int:
        return 0

    def is_import(self, name: str) -> bool:
        return name in self._imports

    def iat_va(self, name: str) -> int:
        return 0


class _Ctx:
    """Контекст второго прохода с реальными адресами."""

    def __init__(self, prog: _Program, plan, section_of):
        self.prog = prog
        self.plan = plan
        self.va = 0
        self._const_cache: dict[str, int] = {}
        self._busy: set[str] = set()

    def here(self) -> int:
        return self.va

    def is_import(self, name: str) -> bool:
        return self.plan["iat"].__contains__(name)

    def iat_va(self, name: str) -> int:
        try:
            return self.plan["iat"][name]
        except KeyError:
            raise AsmError(f"{name!r} не объявлен в ИМПОРТ")

    def resolve_sym(self, name: str) -> int:
        if name in self.prog.labels:
            sec, off = self.prog.labels[name]
            return self.plan["section_va"](sec) + off
        if name in self.prog.consts:
            if name in self._const_cache:
                return self._const_cache[name]
            if name in self._busy:
                raise AsmError(f"циклическая константа {name!r}")
            self._busy.add(name)
            expr, sec, off = self.prog.consts[name]
            sub = _ConstCtx(self, self.plan["section_va"](sec) + off)
            v = eval_expr(expr, sub)
            self._busy.discard(name)
            self._const_cache[name] = v
            return v
        raise AsmError(f"неизвестный символ {name!r}")


class _ConstCtx:
    """Контекст вычисления константы: $ = адрес места её определения."""

    def __init__(self, parent: _Ctx, here_va: int):
        self._p = parent
        self._here = here_va

    @property
    def va(self) -> int:
        return self._here

    def here(self) -> int:
        return self._here

    def resolve_sym(self, name: str) -> int:
        return self._p.resolve_sym(name)

    def is_import(self, name: str) -> bool:
        return self._p.is_import(name)

    def iat_va(self, name: str) -> int:
        return self._p.iat_va(name)


def _data_size(d: Dir, ctx) -> int:
    """Размер директивы данных в байтах."""
    if d.name == "БАЙТ":
        n = 0
        for a in d.args:
            n += len(a.encode("utf-8")) if isinstance(a, str) else 1
        return n
    if d.name in _DATA_SIZES:
        return _DATA_SIZES[d.name] * len(d.args)
    if d.name == "РЕЗЕРВ":
        return int(eval_expr(d.args[0], ctx))
    return 0


def _encode_data(d: Dir, ctx) -> bytes:
    """Кодирует директиву данных в байты."""
    if d.name in _DATA_SIZES:
        out = bytearray()
        sz = _DATA_SIZES[d.name]
        for a in d.args:
            if isinstance(a, str):
                if d.name != "БАЙТ":
                    raise AsmError(f"{d.name}: строки допустимы только в БАЙТ", d.line)
                out += a.encode("utf-8")
            else:
                v = eval_expr(a, ctx)
                out += (v & ((1 << (sz * 8)) - 1)).to_bytes(sz, "little")
        return bytes(out)
    if d.name == "РЕЗЕРВ":
        return b"\0" * int(eval_expr(d.args[0], ctx))
    raise AsmError(f"директива {d.name} не порождает данных", d.line)


def _first_pass(stmts: list) -> _Program:
    """Первый проход: метки, константы, импорты, смещения, размеры секций."""
    prog = _Program()
    # предсканирование импортов: от них зависит длина инструкции ВЫЗОВ
    for s in stmts:
        if isinstance(s, Dir) and s.name == "ИМПОРТ":
            if len(s.args) < 2:
                raise AsmError("ИМПОРТ: нет функций", s.line)
            prog.imports.append((s.args[0], s.args[1:]))
    dry = _DryCtx({f for _, funcs in prog.imports for f in funcs})
    cur = "код"
    offs = {"код": 0, "данные": 0}
    for s in stmts:
        if isinstance(s, Label):
            if s.name in prog.labels or s.name in prog.consts:
                raise AsmError(f"повторное имя {s.name!r}", s.line)
            prog.labels[s.name] = (cur, offs[cur])
            continue
        if isinstance(s, Equ):
            if s.name in prog.labels or s.name in prog.consts:
                raise AsmError(f"повторное имя {s.name!r}", s.line)
            prog.consts[s.name] = (s.expr, cur, offs[cur])
            continue
        if isinstance(s, Dir):
            if s.name == "СЕКЦИЯ":
                key = str(s.args[0]).lower()
                if key not in SECTIONS:
                    raise AsmError(
                        f"неизвестная секция {s.args[0]!r} (код/данные)", s.line
                    )
                cur = SECTIONS[key]
                continue
            if s.name == "ИМПОРТ":
                continue  # уже собраны при предсканировании
            if s.name == "ВХОД":
                if not isinstance(s.args[0], Sym):
                    raise AsmError("ВХОД: ожидалась метка", s.line)
                prog.entry = s.args[0].name
                continue
            if s.name == "ВЫРОВНЯТЬ":
                al = int(eval_expr(s.args[0], dry))
                if al <= 0 or al & (al - 1):
                    raise AsmError("ВЫРОВНЯТЬ: степень двойки", s.line)
                pad = (-offs[cur]) % al
                prog.placed.append(_Placed(s, cur, offs[cur], pad))
                offs[cur] += pad
                continue
            if s.name in _DATA_SIZES or s.name == "РЕЗЕРВ":
                size = _data_size(s, dry)
                prog.placed.append(_Placed(s, cur, offs[cur], size))
                offs[cur] += size
                continue
            raise AsmError(f"директива {s.name} не поддержана", s.line)
        if isinstance(s, Instr):
            size = len(encode(s, dry))
            prog.placed.append(_Placed(s, cur, offs[cur], size))
            offs[cur] += size
            continue
    prog.sizes = offs
    if prog.entry is None:
        prog.entry = "старт"
    if prog.entry not in prog.labels:
        raise AsmError(f"точка входа {prog.entry!r} не найдена")
    return prog


def assemble(source: str, target: str = "windows") -> bytes:
    """Ассемблирует исходный текст в байты исполняемого файла.

    target: 'windows' (PE64) или 'linux' (ELF64).
    """
    if target == "windows":
        from . import emit_pe as emitter
    elif target == "linux":
        from . import emit_elf as emitter
    else:
        raise AsmError(f"неизвестная цель {target!r} (windows/linux)")
    stmts = parse(source)
    prog = _first_pass(stmts)
    text_size = prog.sizes.get("код", 0)
    data_size = prog.sizes.get("данные", 0)
    entry_sec, entry_off = prog.labels[prog.entry]
    if entry_sec != "код":
        raise AsmError("точка входа должна быть в секции кода")
    plan = emitter.plan(text_size, data_size, prog.imports, entry_off)
    ctx = _Ctx(prog, plan, None)
    # второй проход: реальные адреса
    blobs = {"код": bytearray(text_size), "данные": bytearray(data_size)}
    for p in prog.placed:
        s = p.stmt
        ctx.va = plan["section_va"](p.section) + p.offset
        if isinstance(s, Instr):
            data = encode(s, ctx)
        elif isinstance(s, Dir) and s.name == "ВЫРОВНЯТЬ":
            data = b"\0" * p.size
        else:
            data = _encode_data(s, ctx)
        if len(data) != p.size:
            raise AsmError(
                f"внутренняя ошибка: размер изменился ({len(data)} != {p.size})",
                getattr(s, "line", None),
            )
        blobs[p.section][p.offset : p.offset + p.size] = data
    return emitter.build(plan, bytes(blobs["код"]), bytes(blobs["данные"]))
