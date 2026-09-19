"""Кодировщик инструкций x86-64 для русского ассемблера РАСМ.

Переводит оператор Instr в последовательность байтов машинного кода.
Поддерживает: REX-префиксы, ModRM/SIB, RIP-относительную адресацию,
относительные переходы и вызовы импортированных функций через IAT.

Размер каждой инструкции определяется только типами операндов
(не значениями), поэтому двухпроходное ассемблирование корректно.
"""

from __future__ import annotations

import struct

from .errors import AsmError
from .expr import Expr, Sym, eval_expr, has_sym
from .parser import Imm, Instr, Mem, Reg

# --- Таблицы мнемоник --------------------------------------------------------

# Бинарные арифметико-логические: русская мнемоника -> код группы
BINOP = {
    "ДОБ": 0,  # add
    "ИЛИ": 1,  # or
    "ДОБП": 2,  # adc (с переносом)
    "ВЫЧП": 3,  # sbb (с заёмом)
    "И": 4,  # and
    "ВЫЧ": 5,  # sub
    "ИИЛИ": 6,  # xor (исключающее ИЛИ)
    "СРАВ": 7,  # cmp
}

# Унарные F7/F6: мнемоника -> поле reg в ModRM
UNARY = {
    "НЕ": 2,  # not
    "ОТР": 3,  # neg
    "УМНБ": 4,  # mul (беззнаковое)
    "ДЕЛБ": 6,  # div (беззнаковое)
    "ДЕЛ": 7,  # idiv (знаковое)
}

# Сдвиги и циклические сдвиги: мнемоника -> поле reg в ModRM
SHIFT = {
    "ВРЛ": 0,  # rol
    "ВРП": 1,  # ror
    "СДЛ": 4,  # shl/sal
    "СДП": 5,  # shr
    "СДПА": 7,  # sar (арифметический)
}

# Условные переходы: мнемоника -> код условия
JCC = {
    "ПЕРЕПОЛН": 0x0,  # jo
    "НЕПЕРЕПОЛН": 0x1,  # jno
    "НИЖЕ": 0x2,  # jb/jnae
    "ПЕРЕНОС": 0x2,  # jc
    "НЕНИЖЕ": 0x3,  # jnb/jae
    "ВЫШРАВ": 0x3,  # jae
    "НЕПЕРЕНОС": 0x3,  # jnc
    "РАВНО": 0x4,  # je/jz
    "НОЛЬ": 0x4,  # jz
    "НЕРАВНО": 0x5,  # jne/jnz
    "НЕНОЛЬ": 0x5,  # jnz
    "НИЖРАВ": 0x6,  # jbe
    "НЕВЫШЕ": 0x6,  # jna
    "ВЫШЕ": 0x7,  # ja
    "НЕНИЖРАВ": 0x7,  # jnbe
    "ЗНАК": 0x8,  # js
    "НЕЗНАК": 0x9,  # jns
    "ЧЁТ": 0xA,  # jp
    "ЧЕТ": 0xA,  # jp (без диакритики)
    "НЕЧЁТ": 0xB,  # jnp
    "НЕЧЕТ": 0xB,  # jnp
    "МЕНЬШЕ": 0xC,  # jl
    "БОЛРАВ": 0xD,  # jge
    "НЕМЕНЬШЕ": 0xD,  # jnl
    "МЕНРАВ": 0xE,  # jle
    "НЕБОЛЬШЕ": 0xE,  # jng
    "БОЛЬШЕ": 0xF,  # jg
    "НЕМЕНРАВ": 0xF,  # jnle
}

# Инструкции без операндов: мнемоника -> байты
NULLARY = {
    "НОП": b"\x90",  # nop
    "СТОП": b"\xf4",  # hlt
    "ПРЕРЫВ": b"\xcc",  # int3
    "СИСВЫЗОВ": b"\x0f\x05",  # syscall
    "ПОКИНЬ": b"\xc9",  # leave
    "РАСШ": b"\x48\x99",  # cqo (rdx:rax <- знак rax)
    "РАСШД": b"\x99",  # cdq (edx:eax <- знак eax)
}


def _check_range(v: int, bits: int, signed: bool, line: int) -> None:
    """Проверяет, что значение помещается в заданную разрядность."""
    if signed:
        lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    else:
        lo, hi = 0, (1 << bits) - 1
    if not (lo <= v <= hi):
        raise AsmError(f"значение {v} не помещается в {bits} бит", line)


def _check_flex(v: int, bits: int, line: int) -> None:
    """Гибкая проверка: значение может быть знаковым или беззнаковым.

    Например, для 32 бит допустимы и -1, и 0xFFFFFFFF.
    """
    lo, hi = -(1 << (bits - 1)), (1 << bits) - 1
    if not (lo <= v <= hi):
        raise AsmError(f"значение {v} не помещается в {bits} бит", line)


def _imm(v: int, n: int) -> bytes:
    """Непосредственное значение в little-endian (по модулю 2^(8n))."""
    return (v & ((1 << (n * 8)) - 1)).to_bytes(n, "little")


def _rex(w: int, r: int, x: int, b: int, force: bool = False) -> bytes:
    """Байт REX-префикса; пустая строка, если префикс не нужен."""
    v = 0x40 | (w << 3) | (r << 2) | (x << 1) | b
    if v == 0x40 and not force:
        return b""
    return bytes([v])


def _sib(scale: int, index: int, base: int) -> int:
    """Байт SIB."""
    return ({1: 0, 2: 1, 4: 2, 8: 3}[scale] << 6) | ((index & 7) << 3) | (base & 7)


class _Enc:
    """Состояние кодирования одной инструкции."""

    def __init__(self, ctx, line: int):
        self.ctx = ctx
        self.line = line
        self.patches: list[tuple[int, Expr]] = []  # (позиция, выражение цели)

    def rip_patch(self, tail: bytearray, expr: Expr) -> None:
        """Запоминает место disp32 для RIP-относительной адресации."""
        self.patches.append((len(tail), expr))
        tail += b"\0" * 4

    def rm(self, tail: bytearray, op, reg_field: int) -> tuple[int, int]:
        """Кодирует операнд r/m (регистр или память) в tail.

        Возвращает (rex_x, rex_b) — расширенные биты индексного и базового
        регистров для REX-префикса.
        """
        if isinstance(op, Reg):
            tail.append(0xC0 | (reg_field << 3) | (op.num & 7))
            return 0, op.num >> 3
        mem: Mem = op
        if mem.index is not None and (mem.index.num & 7) == 4:
            raise AsmError("УКС/rsp/r12 не может быть индексным регистром", self.line)
        base = mem.base.num if mem.base is not None else None
        index = mem.index.num if mem.index is not None else None
        # RIP-относительная: [метка] — только смещение с символом
        if base is None and index is None:
            if mem.disp is not None and has_sym(mem.disp):
                tail.append(reg_field << 3 | 0x05)  # mod=00, rm=101
                self.rip_patch(tail, mem.disp)
                return 0, 0
            d = eval_expr(mem.disp, self.ctx) if mem.disp is not None else 0
            tail.append(reg_field << 3 | 0x04)  # mod=00, rm=100 + SIB
            tail.append(_sib(1, 4, 5))  # без базы и индекса: disp32
            tail += _imm(d, 4)
            return 0, 0
        if base is None:
            # [индекс*масштаб + disp32]
            d = eval_expr(mem.disp, self.ctx) if mem.disp is not None else 0
            tail.append(reg_field << 3 | 0x04)
            tail.append(_sib(mem.scale, index, 5))
            tail += _imm(d, 4)
            return index >> 3, 0
        # есть базовый регистр
        d: int | None = None
        if mem.disp is not None:
            d = eval_expr(mem.disp, self.ctx)
            if has_sym(mem.disp):
                raise AsmError(
                    "метку нельзя складывать с регистром в адресе", self.line
                )
        need_sib = (base & 7) == 4 or index is not None
        if d is None:
            if (base & 7) == 5:  # rbp/r13 без смещения недоступны
                mod, disp, dsz = 1, 0, 1
            else:
                mod, disp, dsz = 0, 0, 0
        elif -128 <= d <= 127:
            mod, disp, dsz = 1, d, 1
        else:
            mod, disp, dsz = 2, d, 4
        tail.append((mod << 6) | (reg_field << 3) | (4 if need_sib else base & 7))
        if need_sib:
            tail.append(_sib(mem.scale, index if index is not None else 4, base))
        if dsz:
            tail += _imm(disp, dsz)
        return (index >> 3) if index is not None else 0, base >> 3


def _op_size(ops, line: int) -> int:
    """Определяет размер операции по операндам."""
    for o in ops:
        if isinstance(o, Reg):
            return o.size
        if isinstance(o, Mem) and o.size is not None:
            return o.size
    raise AsmError(
        "не удаётся определить размер — укажите БАЙТ/СЛОВО/ДВСЛОВО/КВАД", line
    )


def _need_rex8(op) -> bool:
    """Проверяет, нужен ли REX для 8-битного регистра (spl/bpl/sil/dil/r8b+)."""
    return isinstance(op, Reg) and op.size == 1 and op.need_rex


def _finish(
    enc: _Enc,
    ins: Instr,
    prefix66: bool,
    rex: bytes,
    opcode: bytes,
    tail: bytearray,
    imm: bytes = b"",
) -> bytes:
    """Собирает инструкцию и заполняет RIP-относительные смещения."""
    out = bytearray()
    if prefix66:
        out.append(0x66)
    out += rex
    out += opcode
    base = len(out)
    out += tail
    out += imm
    for pos, expr in enc.patches:
        target = eval_expr(expr, enc.ctx)
        disp = target - (enc.ctx.va + len(out))
        _check_range(disp, 32, True, ins.line)
        out[base + pos : base + pos + 4] = struct.pack("<i", disp)
    return bytes(out)


def _enc_rm_reg(enc, ins, opcode: int, rm_op, reg_op, imm: bytes = b"") -> bytes:
    """Кодирует форму «r/m, reg» или «reg, r/m» (opcode /r)."""
    tail = bytearray()
    x, b = enc.rm(tail, rm_op, reg_op.num & 7)
    size = reg_op.size
    rex = _rex(
        1 if size == 8 else 0,
        reg_op.num >> 3,
        x,
        b,
        force=_need_rex8(rm_op) or _need_rex8(reg_op),
    )
    return _finish(enc, ins, size == 2, rex, bytes([opcode]), tail, imm)


def _enc_binop(enc, ins, code: int) -> bytes:
    """Кодирует бинарные арифметико-логические инструкции (add..cmp)."""
    a, b = ins.ops
    if isinstance(a, Reg) and isinstance(b, (Reg, Mem)):
        if isinstance(b, Reg) and a.size != b.size:
            raise AsmError("размеры регистров не совпадают", ins.line)
        opc = code * 8 + (2 if a.size == 1 else 3)  # reg <- r/m
        return _enc_rm_reg(enc, ins, opc, b, a)
    if isinstance(a, Mem) and isinstance(b, Reg):
        size = b.size
        if a.size is not None and a.size != size:
            raise AsmError("размер памяти не совпадает с регистром", ins.line)
        opc = code * 8 + (0 if size == 1 else 1)  # r/m <- reg
        return _enc_rm_reg(enc, ins, opc, a, b)
    if isinstance(a, (Reg, Mem)) and isinstance(b, Imm):
        size = a.size if isinstance(a, Reg) else _op_size([a], ins.line)
        v = eval_expr(b.expr, enc.ctx)
        if size == 1:
            _check_range(v, 8, True, ins.line)
            opc, im = 0x80, _imm(v, 1)
        else:
            _check_range(v, 32, True, ins.line)
            opc, im = 0x81, _imm(v, 4)
        tail = bytearray()
        x, r_b = enc.rm(tail, a, code)
        rex = _rex(1 if size == 8 else 0, 0, x, r_b, force=_need_rex8(a))
        return _finish(enc, ins, size == 2, rex, bytes([opc]), tail, im)
    raise AsmError(f"{ins.mnem}: недопустимое сочетание операндов", ins.line)


def _enc_mov(enc, ins) -> bytes:
    """Кодирует ПЕР (mov)."""
    a, b = ins.ops
    if isinstance(a, Reg) and isinstance(b, (Reg, Mem)):
        if isinstance(b, Reg) and a.size != b.size:
            raise AsmError("размеры регистров не совпадают", ins.line)
        opc = 0x8A if a.size == 1 else 0x8B
        return _enc_rm_reg(enc, ins, opc, b, a)
    if isinstance(a, Mem) and isinstance(b, Reg):
        opc = 0x88 if b.size == 1 else 0x89
        return _enc_rm_reg(enc, ins, opc, a, b)
    if isinstance(a, Reg) and isinstance(b, Imm):
        # решение о кодировке — по типу выражения (has_sym), значение
        # вычисляется всегда: в первом проходе символы дают 0, размер
        # инструкции от этого не меняется
        sym = has_sym(b.expr)
        v = eval_expr(b.expr, enc.ctx)
        if a.size == 1:
            _check_flex(v, 8, ins.line)
            opc = 0xB0 + (a.num & 7)
            rex = _rex(0, 0, 0, a.num >> 3, force=_need_rex8(a))
            return _finish(enc, ins, False, rex, bytes([opc]), bytearray(), _imm(v, 1))
        if a.size == 8 and (sym or not (-0x80000000 <= v <= 0x7FFFFFFF)):
            # полное 64-битное значение: B8+r с imm64
            opc = 0xB8 + (a.num & 7)
            rex = _rex(1, 0, 0, a.num >> 3)
            return _finish(enc, ins, False, rex, bytes([opc]), bytearray(), _imm(v, 8))
        # 16/32 бита или знакорасширяемое imm32: C7 /0
        if a.size == 2:
            _check_flex(v, 16, ins.line)
        elif a.size == 4:
            _check_flex(v, 32, ins.line)
        else:
            _check_range(v, 32, True, ins.line)
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 0)
        rex = _rex(1 if a.size == 8 else 0, 0, x, r_b)
        return _finish(
            enc, ins, a.size == 2, rex, b"\xc7", tail, _imm(v, 4 if a.size != 2 else 2)
        )
    if isinstance(a, Mem) and isinstance(b, Imm):
        size = _op_size([a], ins.line)
        v = eval_expr(b.expr, enc.ctx)
        if size == 8:
            _check_range(v, 32, True, ins.line)  # imm32 знакорасширяется
        else:
            _check_flex(v, 8 if size == 1 else size * 8, ins.line)
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 0)
        rex = _rex(1 if size == 8 else 0, 0, x, r_b)
        opc = 0xC6 if size == 1 else 0xC7
        return _finish(
            enc,
            ins,
            size == 2,
            rex,
            bytes([opc]),
            tail,
            _imm(v, 1 if size == 1 else (2 if size == 2 else 4)),
        )
    raise AsmError("ПЕР: недопустимое сочетание операндов", ins.line)


def _enc_unary(enc, ins, code: int) -> bytes:
    """Кодирует унарные инструкции группы F7/F6 (НЕ, ОТР, ДЕЛ и др.)."""
    (a,) = ins.ops
    if not isinstance(a, (Reg, Mem)):
        raise AsmError(f"{ins.mnem}: ожидался регистр или память", ins.line)
    size = a.size if isinstance(a, Reg) else _op_size([a], ins.line)
    opc = 0xF6 if size == 1 else 0xF7
    tail = bytearray()
    x, r_b = enc.rm(tail, a, code)
    rex = _rex(1 if size == 8 else 0, 0, x, r_b, force=_need_rex8(a))
    return _finish(enc, ins, size == 2, rex, bytes([opc]), tail)


def _enc_imul(enc, ins) -> bytes:
    """Кодирует УМН (imul): 1, 2 или 3 операнда."""
    ops = ins.ops
    if len(ops) == 1:
        return _enc_unary(enc, ins, 5)
    if len(ops) == 2 and isinstance(ops[0], Reg) and isinstance(ops[1], (Reg, Mem)):
        a, b = ops
        tail = bytearray()
        x, r_b = enc.rm(tail, b, a.num & 7)
        rex = _rex(1 if a.size == 8 else 0, a.num >> 3, x, r_b)
        return _finish(enc, ins, a.size == 2, rex, b"\x0f\xaf", tail)
    if (
        len(ops) == 3
        and isinstance(ops[0], Reg)
        and isinstance(ops[1], (Reg, Mem))
        and isinstance(ops[2], Imm)
    ):
        a, b, c = ops
        v = eval_expr(c.expr, enc.ctx)
        _check_range(v, 32, True, ins.line)
        tail = bytearray()
        x, r_b = enc.rm(tail, b, a.num & 7)
        rex = _rex(1 if a.size == 8 else 0, a.num >> 3, x, r_b)
        im = _imm(v, 2 if a.size == 2 else 4)
        return _finish(enc, ins, a.size == 2, rex, b"\x69", tail, im)
    raise AsmError("УМН: недопустимое сочетание операндов", ins.line)


def _enc_shift(enc, ins, code: int) -> bytes:
    """Кодирует сдвиги: СДЛ/СДП/СДПА/ВРЛ/ВРП по числу или по СЧТБ (cl)."""
    a, b = ins.ops
    if not isinstance(a, (Reg, Mem)):
        raise AsmError(f"{ins.mnem}: первый операнд — регистр или память", ins.line)
    size = a.size if isinstance(a, Reg) else _op_size([a], ins.line)
    tail = bytearray()
    x, r_b = enc.rm(tail, a, code)
    rex = _rex(1 if size == 8 else 0, 0, x, r_b, force=_need_rex8(a))
    if isinstance(b, Imm):
        v = eval_expr(b.expr, enc.ctx)
        _check_range(v, 8, False, ins.line)
        opc = 0xC0 if size == 1 else 0xC1
        return _finish(enc, ins, size == 2, rex, bytes([opc]), tail, _imm(v, 1))
    if isinstance(b, Reg) and b.num == 1 and b.size == 1:  # cl / СЧТБ
        opc = 0xD2 if size == 1 else 0xD3
        return _finish(enc, ins, size == 2, rex, bytes([opc]), tail)
    raise AsmError(f"{ins.mnem}: счётчик — число или СЧТБ (cl)", ins.line)


def _enc_incdec(enc, ins, code: int) -> bytes:
    """Кодирует УВЕЛ (inc, /0) и УМЕН (dec, /1)."""
    (a,) = ins.ops
    if not isinstance(a, (Reg, Mem)):
        raise AsmError(f"{ins.mnem}: ожидался регистр или память", ins.line)
    size = a.size if isinstance(a, Reg) else _op_size([a], ins.line)
    opc = 0xFE if size == 1 else 0xFF
    tail = bytearray()
    x, r_b = enc.rm(tail, a, code)
    rex = _rex(1 if size == 8 else 0, 0, x, r_b, force=_need_rex8(a))
    return _finish(enc, ins, size == 2, rex, bytes([opc]), tail)


def _enc_push(enc, ins) -> bytes:
    """Кодирует ВСТЕК (push): регистр, память или число."""
    (a,) = ins.ops
    if isinstance(a, Reg):
        if a.size == 2:
            return _finish(
                enc,
                ins,
                True,
                _rex(0, 0, 0, a.num >> 3),
                bytes([0x50 + (a.num & 7)]),
                bytearray(),
            )
        if a.size != 8:
            raise AsmError("ВСТЕК: регистр должен быть 16- или 64-битным", ins.line)
        return _finish(
            enc,
            ins,
            False,
            _rex(0, 0, 0, a.num >> 3),
            bytes([0x50 + (a.num & 7)]),
            bytearray(),
        )
    if isinstance(a, Mem):
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 6)
        return _finish(enc, ins, False, _rex(0, 0, x, r_b), b"\xff", tail)
    if isinstance(a, Imm):
        v = eval_expr(a.expr, enc.ctx)
        _check_range(v, 32, True, ins.line)
        return _finish(enc, ins, False, b"", b"\x68", bytearray(), _imm(v, 4))
    raise AsmError("ВСТЕК: недопустимый операнд", ins.line)


def _enc_pop(enc, ins) -> bytes:
    """Кодирует ИЗСТЕКА (pop): регистр или память."""
    (a,) = ins.ops
    if isinstance(a, Reg):
        if a.size not in (2, 8):
            raise AsmError("ИЗСТЕКА: регистр должен быть 16- или 64-битным", ins.line)
        return _finish(
            enc,
            ins,
            a.size == 2,
            _rex(0, 0, 0, a.num >> 3),
            bytes([0x58 + (a.num & 7)]),
            bytearray(),
        )
    if isinstance(a, Mem):
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 0)
        return _finish(enc, ins, False, _rex(0, 0, x, r_b), b"\x8f", tail)
    raise AsmError("ИЗСТЕКА: недопустимый операнд", ins.line)


def _enc_call(enc, ins) -> bytes:
    """Кодирует ВЫЗОВ (call): метка, импорт, регистр или память."""
    (a,) = ins.ops
    if isinstance(a, Imm):
        if isinstance(a.expr, Sym) and enc.ctx.is_import(a.expr.name):
            # вызов импортированной функции: call [rip + IAT]
            tail = bytearray()
            tail.append(2 << 3 | 0x05)  # FF /2, mod=00 rm=101
            enc.rip_patch(tail, _IatExpr(a.expr.name))
            return _finish(enc, ins, False, b"", b"\xff", tail)
        tail = bytearray()
        enc.rip_patch(tail, a.expr)
        return _finish(enc, ins, False, b"", b"\xe8", tail)
    if isinstance(a, (Reg, Mem)):
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 2)
        return _finish(enc, ins, False, _rex(0, 0, x, r_b), b"\xff", tail)
    raise AsmError("ВЫЗОВ: недопустимый операнд", ins.line)


def _enc_jmp(enc, ins) -> bytes:
    """Кодирует ПРЫГ (jmp): метка, регистр или память."""
    (a,) = ins.ops
    if isinstance(a, Imm):
        tail = bytearray()
        enc.rip_patch(tail, a.expr)
        return _finish(enc, ins, False, b"", b"\xe9", tail)
    if isinstance(a, (Reg, Mem)):
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 4)
        return _finish(enc, ins, False, _rex(0, 0, x, r_b), b"\xff", tail)
    raise AsmError("ПРЫГ: недопустимый операнд", ins.line)


def _enc_jcc(enc, ins, cc: int) -> bytes:
    """Кодирует условный переход (0F 8x rel32)."""
    (a,) = ins.ops
    if not isinstance(a, Imm):
        raise AsmError(f"{ins.mnem}: ожидалась метка", ins.line)
    tail = bytearray()
    enc.rip_patch(tail, a.expr)
    return _finish(enc, ins, False, b"", bytes([0x0F, 0x80 + cc]), tail)


def _enc_ret(enc, ins) -> bytes:
    """Кодирует ВОЗВРАТ (ret), с необязательным числом байт стека."""
    if not ins.ops:
        return b"\xc3"
    (a,) = ins.ops
    if not isinstance(a, Imm):
        raise AsmError("ВОЗВРАТ: ожидалось число", ins.line)
    v = eval_expr(a.expr, enc.ctx)
    _check_range(v, 16, False, ins.line)
    return b"\xc2" + _imm(v, 2)


def _enc_lea(enc, ins) -> bytes:
    """Кодирует АДР (lea): регистр <- адрес памяти."""
    a, b = ins.ops
    if not isinstance(a, Reg) or not isinstance(b, Mem):
        raise AsmError("АДР: ожидалось «регистр, [адрес]»", ins.line)
    return _enc_rm_reg(enc, ins, 0x8D, b, a)


def _enc_xchg(enc, ins) -> bytes:
    """Кодирует ОБМЕН (xchg)."""
    a, b = ins.ops
    if isinstance(a, Reg) and isinstance(b, (Reg, Mem)):
        if isinstance(b, Reg) and a.size != b.size:
            raise AsmError("размеры регистров не совпадают", ins.line)
        opc = 0x86 if a.size == 1 else 0x87
        return _enc_rm_reg(enc, ins, opc, b, a)
    if isinstance(a, Mem) and isinstance(b, Reg):
        opc = 0x86 if b.size == 1 else 0x87
        return _enc_rm_reg(enc, ins, opc, a, b)
    raise AsmError("ОБМЕН: недопустимое сочетание операндов", ins.line)


def _enc_test(enc, ins) -> bytes:
    """Кодирует ПРОВ (test)."""
    a, b = ins.ops
    if isinstance(a, (Reg, Mem)) and isinstance(b, Reg):
        opc = 0x84 if b.size == 1 else 0x85
        return _enc_rm_reg(enc, ins, opc, a, b)
    if isinstance(a, (Reg, Mem)) and isinstance(b, Imm):
        size = a.size if isinstance(a, Reg) else _op_size([a], ins.line)
        v = eval_expr(b.expr, enc.ctx)
        _check_range(v, 8 if size == 1 else 32, True, ins.line)
        tail = bytearray()
        x, r_b = enc.rm(tail, a, 0)
        rex = _rex(1 if size == 8 else 0, 0, x, r_b, force=_need_rex8(a))
        opc = 0xF6 if size == 1 else 0xF7
        return _finish(
            enc,
            ins,
            size == 2,
            rex,
            bytes([opc]),
            tail,
            _imm(v, 1 if size == 1 else (2 if size == 2 else 4)),
        )
    raise AsmError("ПРОВ: недопустимое сочетание операндов", ins.line)


class _IatExpr(Expr):
    """Псевдовыражение: адрес ячейки IAT для импортированной функции."""

    def __init__(self, name: str):
        self.name = name


def encode(ins: Instr, ctx) -> bytes:
    """Кодирует одну инструкцию в байты машинного кода.

    ctx: контекст с полями va (адрес инструкции), resolve_sym, here,
    is_import, iat_va. При проходе «на размер» resolve_sym может
    возвращать 0 — длина инструкции от этого не зависит.
    """
    enc = _Enc(ctx, ins.line)
    # подменяем eval_expr, чтобы понимал _IatExpr
    enc.ctx = _CtxWrap(ctx)
    m = ins.mnem
    n = len(ins.ops)
    try:
        if m in NULLARY:
            if n != 0:
                raise AsmError(f"{m}: операнды не нужны", ins.line)
            return NULLARY[m]
        if m in BINOP:
            if n != 2:
                raise AsmError(f"{m}: нужно два операнда", ins.line)
            return _enc_binop(enc, ins, BINOP[m])
        if m == "ПЕР":
            if n != 2:
                raise AsmError("ПЕР: нужно два операнда", ins.line)
            return _enc_mov(enc, ins)
        if m in UNARY:
            if n != 1:
                raise AsmError(f"{m}: нужен один операнд", ins.line)
            return _enc_unary(enc, ins, UNARY[m])
        if m == "УМН":
            return _enc_imul(enc, ins)
        if m in SHIFT:
            if n != 2:
                raise AsmError(f"{m}: нужно два операнда", ins.line)
            return _enc_shift(enc, ins, SHIFT[m])
        if m == "УВЕЛ":
            if n != 1:
                raise AsmError("УВЕЛ: нужен один операнд", ins.line)
            return _enc_incdec(enc, ins, 0)
        if m == "УМЕН":
            if n != 1:
                raise AsmError("УМЕН: нужен один операнд", ins.line)
            return _enc_incdec(enc, ins, 1)
        if m == "ВСТЕК":
            if n != 1:
                raise AsmError("ВСТЕК: нужен один операнд", ins.line)
            return _enc_push(enc, ins)
        if m == "ИЗСТЕКА":
            if n != 1:
                raise AsmError("ИЗСТЕКА: нужен один операнд", ins.line)
            return _enc_pop(enc, ins)
        if m == "ВЫЗОВ":
            if n != 1:
                raise AsmError("ВЫЗОВ: нужен один операнд", ins.line)
            return _enc_call(enc, ins)
        if m == "ВОЗВРАТ":
            return _enc_ret(enc, ins)
        if m == "ПРЫГ":
            if n != 1:
                raise AsmError("ПРЫГ: нужен один операнд", ins.line)
            return _enc_jmp(enc, ins)
        if m in JCC:
            if n != 1:
                raise AsmError(f"{m}: нужен один операнд (метка)", ins.line)
            return _enc_jcc(enc, ins, JCC[m])
        if m == "АДР":
            if n != 2:
                raise AsmError("АДР: нужно два операнда", ins.line)
            return _enc_lea(enc, ins)
        if m == "ОБМЕН":
            if n != 2:
                raise AsmError("ОБМЕН: нужно два операнда", ins.line)
            return _enc_xchg(enc, ins)
        if m == "ПРОВ":
            if n != 2:
                raise AsmError("ПРОВ: нужно два операнда", ins.line)
            return _enc_test(enc, ins)
        raise AsmError(f"неизвестная мнемоника {m!r}", ins.line)
    except AsmError:
        raise


class _CtxWrap:
    """Обёртка контекста: eval_expr с поддержкой _IatExpr."""

    def __init__(self, ctx):
        self._ctx = ctx

    @property
    def va(self) -> int:
        return self._ctx.va

    def resolve_sym(self, name: str) -> int:
        return self._ctx.resolve_sym(name)

    def here(self) -> int:
        return self._ctx.here()

    def is_import(self, name: str) -> bool:
        return self._ctx.is_import(name)

    def iat_va(self, name: str) -> int:
        return self._ctx.iat_va(name)


# eval_expr вызывается из encoder через _eval_special для поддержки IAT
_orig_eval = eval_expr


def eval_expr(e, ctx):  # noqa: F811 — расширенная версия для encoder
    """Вычисляет выражение; дополнительно понимает _IatExpr."""
    if isinstance(e, _IatExpr):
        return ctx.iat_va(e.name)
    return _orig_eval(e, ctx)
