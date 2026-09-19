"""Тесты кодировщика x86-64: сверка байтов с эталонными кодировками."""

import pytest

from asm_rus.encoder import encode
from asm_rus.errors import AsmError
from asm_rus.parser import Instr, parse


class _Ctx:
    """Фиктивный контекст: метки по адресу 0x140002000, IAT — 0x140002100."""

    va = 0x140001000

    def resolve_sym(self, name):
        return 0x140002000

    def here(self):
        return self.va

    def is_import(self, name):
        return name == "GetStdHandle"

    def iat_va(self, name):
        return 0x140002100


def enc(src: str) -> bytes:
    """Кодирует единственную инструкцию из строки."""
    ins = [s for s in parse(src) if isinstance(s, Instr)][0]
    return encode(ins, _Ctx())


def h(b: bytes) -> str:
    return b.hex(" ")


@pytest.mark.parametrize(
    "src, expected",
    [
        ("НОП", "90"),
        ("СТОП", "f4"),
        ("ПРЕРЫВ", "cc"),
        ("СИСВЫЗОВ", "0f 05"),
        ("ВОЗВРАТ", "c3"),
        ("ПОКИНЬ", "c9"),
        ("ПЕР АКК, БАЗ", "48 8b c3"),  # mov rax, rbx
        ("ПЕР БАЗ, АКК", "48 8b d8"),  # mov rbx, rax
        ("ПЕР СЧТМ, -11", "c7 c1 f5 ff ff ff"),  # mov ecx, -11
        ("ПЕР Р8М, 5", "41 c7 c0 05 00 00 00"),  # mov r8d, 5
        ("ВСТЕК АКК", "50"),  # push rax
        ("ВСТЕК Р15", "41 57"),  # push r15
        ("ИЗСТЕКА АКК", "58"),  # pop rax
        ("ИИЛИ СЧТМ, СЧТМ", "33 c9"),  # xor ecx, ecx
        ("ВЫЧ УКС, 40", "48 81 ec 28 00 00 00"),  # sub rsp, 40
        ("ДОБ АКК, 5", "48 81 c0 05 00 00 00"),  # add rax, 5
        ("ПЕР [АКК], БАЗ", "48 89 18"),  # mov [rax], rbx
        ("ПЕР АКК, [БАЗ+8]", "48 8b 43 08"),  # mov rax, [rbx+8]
        ("ПЕР АКК, [БАЗ+ИСТ*4+16]", "48 8b 44 b3 10"),
        ("ПЕР КВАД [УКС+32], 0", "48 c7 44 24 20 00 00 00 00"),
        ("УВЕЛ АКК", "48 ff c0"),  # inc rax
        ("УМЕН БАЗ", "48 ff cb"),  # dec rbx
        ("НЕ АКК", "48 f7 d0"),  # not rax
        ("ОТР АКК", "48 f7 d8"),  # neg rax
        ("СДЛ АКК, 3", "48 c1 e0 03"),  # shl rax, 3
        ("ПРОВ АКК, АКК", "48 85 c0"),  # test rax, rax
        ("АДР ДАН, [м]", "48 8d 15 f9 0f 00 00"),  # lea rdx,[rip+м]
        ("ВЫЗОВ GetStdHandle", "ff 15 fa 10 00 00"),  # call [rip+IAT]
        ("ПРЫГ метка", "e9 fb 0f 00 00"),  # jmp rel32
        ("РАВНО метка", "0f 84 fa 0f 00 00"),  # je rel32
        ("МЕНЬШЕ метка", "0f 8c fa 0f 00 00"),  # jl rel32
        ("ОБМЕН АКК, БАЗ", "48 87 c3"),  # xchg rax, rbx
        ("ВЫЗОВ АКК", "ff d0"),  # call rax
    ],
)
def test_encode(src, expected):
    assert h(enc(src)) == expected


def test_неизвестная_мнемоника():
    with pytest.raises(AsmError):
        enc("ЛАЛАЛА АКК")


def test_несовпадение_размеров():
    with pytest.raises(AsmError):
        enc("ПЕР АКК, БАЗМ")
