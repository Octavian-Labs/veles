"""Эмиттер ELF64 (Linux): статический исполняемый файл без библиотек.

Один сегмент PT_LOAD (RWE) отображает весь файл по базе 0x400000,
поэтому виртуальный адрес = 0x400000 + смещение в файле.
Системные вызовы выполняются инструкцией СИСВЫЗОВ (syscall);
директива ИМПОРТ для Linux не поддерживается.
"""

from __future__ import annotations

import struct

from .errors import AsmError

BASE = 0x400000
EHDR_SIZE = 64
PHDR_SIZE = 56
HDRS = EHDR_SIZE + PHDR_SIZE


def plan(text_size: int, data_size: int, imports: list, entry_off: int) -> dict:
    """Назначает адреса секций: vaddr = BASE + смещение в файле."""
    if imports:
        raise AsmError("ИМПОРТ не поддерживается для цели linux — используйте СИСВЫЗОВ")
    text_va = BASE + HDRS
    data_va = text_va + text_size

    def section_va(name: str) -> int:
        if name == "код":
            return text_va
        if name == "данные":
            return data_va
        raise AsmError(f"неизвестная секция {name!r}")

    return {
        "iat": {},
        "blobs": [],
        "text_va": text_va,
        "data_va": data_va,
        "entry_va": text_va + entry_off,
        "section_va": section_va,
    }


def build(plan: dict, text: bytes, data: bytes) -> bytes:
    """Собирает ELF64: заголовок, один программный заголовок, код, данные."""
    file_size = HDRS + len(text) + len(data)

    ehdr = bytearray(EHDR_SIZE)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 2  # класс: 64 бита
    ehdr[5] = 1  # порядок байт: little-endian
    ehdr[6] = 1  # версия ELF
    ehdr[7] = 0  # OS/ABI: System V
    struct.pack_into("<H", ehdr, 16, 2)  # e_type: EXEC
    struct.pack_into("<H", ehdr, 18, 0x3E)  # e_machine: x86-64
    struct.pack_into("<I", ehdr, 20, 1)  # e_version
    struct.pack_into("<Q", ehdr, 24, plan["entry_va"])
    struct.pack_into("<Q", ehdr, 32, EHDR_SIZE)  # e_phoff
    struct.pack_into("<Q", ehdr, 40, 0)  # e_shoff
    struct.pack_into("<H", ehdr, 52, EHDR_SIZE)  # e_ehsize
    struct.pack_into("<H", ehdr, 54, PHDR_SIZE)  # e_phentsize
    struct.pack_into("<H", ehdr, 56, 1)  # e_phnum
    struct.pack_into("<H", ehdr, 58, 64)  # e_shentsize

    phdr = bytearray(PHDR_SIZE)
    struct.pack_into("<I", phdr, 0, 1)  # p_type: PT_LOAD
    struct.pack_into("<I", phdr, 4, 7)  # p_flags: RWE
    struct.pack_into("<Q", phdr, 8, 0)  # p_offset
    struct.pack_into("<Q", phdr, 16, BASE)  # p_vaddr
    struct.pack_into("<Q", phdr, 24, BASE)  # p_paddr
    struct.pack_into("<Q", phdr, 32, file_size)  # p_filesz
    struct.pack_into("<Q", phdr, 40, file_size)  # p_memsz
    struct.pack_into("<Q", phdr, 48, 0x1000)  # p_align

    return bytes(ehdr) + bytes(phdr) + text + data
