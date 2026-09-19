"""Сквозные тесты: ассемблирование примеров и проверка форматов файлов."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest

from asm_rus.assembler import assemble

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def test_pe_привет_структура():
    """PE64: сигнатуры MZ/PE, машина x86-64, точка входа в .text."""
    src = (EXAMPLES / "привет.асм").read_text(encoding="utf-8")
    data = assemble(src, "windows")
    assert data[:2] == b"MZ"
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_off : pe_off + 4] == b"PE\0\0"
    machine = struct.unpack_from("<H", data, pe_off + 4)[0]
    assert machine == 0x8664
    entry = struct.unpack_from("<I", data, pe_off + 24 + 16)[0]
    assert 0x1000 <= entry < 0x2000


@pytest.mark.skipif(sys.platform != "win32", reason="запуск exe только в Windows")
def test_pe_привет_запуск(tmp_path):
    """Собранный привет.exe реально печатает строку и возвращает 0."""
    src = (EXAMPLES / "привет.асм").read_text(encoding="utf-8")
    exe = tmp_path / "привет.exe"
    exe.write_bytes(assemble(src, "windows"))
    res = subprocess.run([str(exe)], capture_output=True, timeout=15)
    assert res.returncode == 0
    assert res.stdout == "Привет, мир!\r\n".encode("utf-8")


def test_elf_привет_структура():
    """ELF64: магия, тип EXEC, машина x86-64, точка входа за заголовками."""
    src = (EXAMPLES / "привет_linux.асм").read_text(encoding="utf-8")
    data = assemble(src, "linux")
    assert data[:4] == b"\x7fELF"
    assert data[4] == 2 and data[5] == 1  # 64 бита, little-endian
    assert struct.unpack_from("<H", data, 16)[0] == 2  # EXEC
    assert struct.unpack_from("<H", data, 18)[0] == 0x3E  # x86-64
    entry = struct.unpack_from("<Q", data, 24)[0]
    assert entry == 0x400000 + 64 + 56


@pytest.mark.skipif(sys.platform != "linux", reason="запуск ELF только в Linux")
def test_elf_привет_запуск(tmp_path):
    """Собранный ELF реально печатает строку и возвращает 0."""
    src = (EXAMPLES / "привет_linux.асм").read_text(encoding="utf-8")
    elf = tmp_path / "привет"
    elf.write_bytes(assemble(src, "linux"))
    elf.chmod(0o755)
    res = subprocess.run([str(elf)], capture_output=True, timeout=15)
    assert res.returncode == 0
    assert res.stdout == "Привет, мир!\n".encode("utf-8")


def test_ошибка_неизвестный_символ():
    from asm_rus.errors import AsmError

    with pytest.raises(AsmError):
        assemble("СЕКЦИЯ код\nВХОД старт\nстарт:\n ПРЫГ нет_такой\n")
