"""Таблица регистров x86-64 с русскими псевдонимами.

Русские имена регистров (по ролям классической архитектуры):
    АКК — аккумулятор (rax)        УКС — указатель стека (rsp)
    СЧТ — счётчик (rcx)            УКК — указатель кадра (rbp)
    ДАН — данные (rdx)             ИСТ — источник (rsi)
    БАЗ — база (rbx)               ПРМ — приёмник (rdi)
    Р8..Р15 — дополнительные регистры (r8..r15)

Суффиксы размера для русских имён:
    без суффикса — 64 бита, М — 32 бита (младший),
    П — 16 бит (половина), Б — 8 бит (байт).
Примеры: АКК = rax, АККМ = eax, АККП = ax, АККБ = al.
"""

from __future__ import annotations

# имя -> (номер регистра, размер в байтах, требуется ли REX для 8-бит)
REGS: dict[str, tuple[int, int, bool]] = {}

_NAMES = {
    8: ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi"],
    4: ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"],
    2: ["ax", "cx", "dx", "bx", "sp", "bp", "si", "di"],
    1: ["al", "cl", "dl", "bl", "spl", "bpl", "sil", "dil"],
}

for _i in range(8):
    for _size, _tbl in _NAMES.items():
        # spl/bpl/sil/dil требуют байта REX даже без расширенных битов
        _need_rex = _size == 1 and _i >= 4
        REGS[_tbl[_i]] = (_i, _size, _need_rex)

for _i in range(8, 16):
    REGS[f"r{_i}"] = (_i, 8, False)
    REGS[f"r{_i}d"] = (_i, 4, False)
    REGS[f"r{_i}w"] = (_i, 2, False)
    REGS[f"r{_i}b"] = (_i, 1, True)

# Русские псевдонимы в порядке номеров регистров rax..rdi
_RUS = ["АКК", "СЧТ", "ДАН", "БАЗ", "УКС", "УКК", "ИСТ", "ПРМ"]
_SUFFIX = {8: "", 4: "М", 2: "П", 1: "Б"}

for _i, _a in enumerate(_RUS):
    for _size, _suf in _SUFFIX.items():
        _need_rex = _size == 1 and _i >= 4
        REGS[(_a + _suf).lower()] = (_i, _size, _need_rex)

for _i in range(8, 16):
    for _size, _suf in _SUFFIX.items():
        REGS[f"р{_i}{_suf}".lower()] = (_i, _size, _i >= 8)


def lookup(name: str):
    """Возвращает (номер, размер, нужен_rex) по имени регистра или None."""
    return REGS.get(name.lower())
