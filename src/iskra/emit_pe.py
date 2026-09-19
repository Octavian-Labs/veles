"""Эмиттер PE64 (Windows): заголовки PE, секции .text/.data, таблица импортов.

Формат: PE32+ (x86-64). Базовый адрес образа 0x140000000,
выравнивание секций 0x1000, выравнивание в файле 0x200.
Импорты размещаются в секции .data: дескрипторы, ILT, IAT,
таблицы имён (hint/name) и имена DLL.
"""

from __future__ import annotations

import struct

from .errors import AsmError

FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000
IMAGE_BASE = 0x140000000
TEXT_RVA = 0x1000
DOS_LFANEW = 0x80


def _align(v: int, a: int) -> int:
    """Выравнивание вверх."""
    return (v + a - 1) & ~(a - 1)


def plan(text_size: int, data_size: int, imports: list, entry_off: int) -> dict:
    """Назначает RVA секций и ячеек IAT; возвращает план компоновки.

    Раскладка внутри .data (после пользовательских данных):
        дескрипторы импорта -> таблицы ILT -> таблицы IAT ->
        hint/name записи -> имена DLL.
    """
    has_data = data_size > 0 or bool(imports)
    data_rva = TEXT_RVA + _align(max(text_size, 1), SECT_ALIGN) if has_data else 0

    iat: dict[str, int] = {}
    blobs: list[tuple[int, bytes]] = []
    desc_rva = desc_size = iat_rva = iat_size = 0

    if imports:
        pos = _align(data_size, 8)
        # дескрипторы: по одному на DLL + нулевой терминатор
        desc_off = pos
        pos += (len(imports) + 1) * 20
        # таблицы ILT и IAT для каждой DLL
        ilt_offs: list[int] = []
        iat_offs: list[int] = []
        for dll, funcs in imports:
            ilt_offs.append(pos)
            pos += (len(funcs) + 1) * 8
        for dll, funcs in imports:
            iat_offs.append(pos)
            pos += (len(funcs) + 1) * 8
        # hint/name записи и имена DLL
        hint_rva: dict[str, int] = {}
        name_rvas: list[int] = []
        for dll, funcs in imports:
            for f in funcs:
                hint_rva[f] = data_rva + pos
                raw = struct.pack("<H", 0) + f.encode("ascii") + b"\0"
                blobs.append((pos, raw))
                pos += _align(len(raw), 2)
        for dll, funcs in imports:
            name_rvas.append(data_rva + pos)
            raw = dll.encode("ascii") + b"\0"
            blobs.append((pos, raw))
            pos += len(raw)
        # дескрипторы
        desc = bytearray()
        for i, (dll, funcs) in enumerate(imports):
            desc += struct.pack(
                "<IIIII",
                data_rva + ilt_offs[i],  # OriginalFirstThunk -> ILT
                0,
                0,
                name_rvas[i],  # Name -> имя DLL
                data_rva + iat_offs[i],  # FirstThunk -> IAT
            )
        desc += b"\0" * 20
        blobs.append((desc_off, bytes(desc)))
        # ILT и IAT: элементы — RVA hint/name записей
        for i, (dll, funcs) in enumerate(imports):
            ilt = bytearray()
            for f in funcs:
                ilt += struct.pack("<Q", hint_rva[f])
            ilt += b"\0" * 8
            blobs.append((ilt_offs[i], bytes(ilt)))
        for i, (dll, funcs) in enumerate(imports):
            iat_b = bytearray()
            for f in funcs:
                iat_b += struct.pack("<Q", hint_rva[f])
            iat_b += b"\0" * 8
            blobs.append((iat_offs[i], bytes(iat_b)))
            for j, f in enumerate(funcs):
                # в карте IAT — абсолютные адреса (VA), нужные кодировщику
                iat[f] = IMAGE_BASE + data_rva + iat_offs[i] + j * 8
        desc_rva = data_rva + desc_off
        desc_size = (len(imports) + 1) * 20
        iat_rva = data_rva + iat_offs[0]
        iat_size = sum(len(f) + 1 for _, f in imports) * 8
        data_size = pos

    def section_va(name: str) -> int:
        if name == "код":
            return IMAGE_BASE + TEXT_RVA
        if name == "данные":
            return IMAGE_BASE + data_rva
        raise AsmError(f"неизвестная секция {name!r}")

    return {
        "text_rva": TEXT_RVA,
        "data_rva": data_rva,
        "has_data": has_data,
        "data_size": data_size,
        "iat": iat,
        "blobs": blobs,
        "desc": (desc_rva, desc_size),
        "iat_dir": (iat_rva, iat_size),
        "entry_rva": TEXT_RVA + entry_off,
        "section_va": section_va,
    }


def build(plan: dict, text: bytes, data: bytes) -> bytes:
    """Собирает полный PE64-файл из закодированных секций."""
    # вставляем блоки импортов в .data
    data_b = bytearray(data)
    if len(data_b) < plan["data_size"]:
        data_b += b"\0" * (plan["data_size"] - len(data_b))
    for off, blob in plan["blobs"]:
        data_b[off : off + len(blob)] = blob

    nsec = 2 if plan["has_data"] else 1
    headers_size = _align(DOS_LFANEW + 4 + 20 + 240 + 40 * nsec, FILE_ALIGN)
    text_raw = headers_size
    data_raw = text_raw + _align(len(text), FILE_ALIGN)

    text_vsize = len(text)
    data_vsize = len(data_b)
    size_of_image = _align(TEXT_RVA + _align(text_vsize, SECT_ALIGN), SECT_ALIGN)
    if plan["has_data"]:
        size_of_image = plan["data_rva"] + _align(max(data_vsize, 1), SECT_ALIGN)

    # --- DOS-заголовок и стаб ---
    out = bytearray()
    dos = bytearray(DOS_LFANEW)
    dos[0:2] = b"MZ"
    stub_msg = b"This program cannot be run in DOS mode.\r\r\n$"
    dos[0x40 : 0x40 + len(stub_msg)] = stub_msg
    struct.pack_into("<I", dos, 0x3C, DOS_LFANEW)
    out += dos

    # --- PE-сигнатура и заголовок файла ---
    out += b"PE\0\0"
    characteristics = 0x0002 | 0x0020  # EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE
    out += struct.pack("<HHIIIHH", 0x8664, nsec, 0, 0, 0, 240, characteristics)

    # --- опциональный заголовок PE32+ (240 байт) ---
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)  # Magic: PE32+
    opt[2], opt[3] = 14, 0  # версия компоновщика
    struct.pack_into("<I", opt, 4, _align(text_vsize, FILE_ALIGN))
    struct.pack_into("<I", opt, 8, _align(data_vsize, FILE_ALIGN))
    struct.pack_into("<I", opt, 16, plan["entry_rva"])  # AddressOfEntryPoint
    struct.pack_into("<I", opt, 20, TEXT_RVA)  # BaseOfCode
    struct.pack_into("<Q", opt, 24, IMAGE_BASE)  # ImageBase
    struct.pack_into("<I", opt, 32, SECT_ALIGN)
    struct.pack_into("<I", opt, 36, FILE_ALIGN)
    struct.pack_into("<H", opt, 40, 6)  # MajorOperatingSystemVersion
    struct.pack_into("<H", opt, 48, 6)  # MajorSubsystemVersion
    struct.pack_into("<I", opt, 56, size_of_image)
    struct.pack_into("<I", opt, 60, headers_size)
    struct.pack_into("<H", opt, 68, 3)  # Subsystem: консоль
    struct.pack_into("<Q", opt, 72, 0x100000)  # SizeOfStackReserve
    struct.pack_into("<Q", opt, 80, 0x1000)  # SizeOfStackCommit
    struct.pack_into("<Q", opt, 88, 0x100000)  # SizeOfHeapReserve
    struct.pack_into("<Q", opt, 96, 0x1000)  # SizeOfHeapCommit
    struct.pack_into("<I", opt, 108, 16)  # NumberOfRvaAndSizes
    # каталоги данных: [1]=импорт, [12]=IAT
    struct.pack_into("<II", opt, 112 + 1 * 8, *plan["desc"])
    struct.pack_into("<II", opt, 112 + 12 * 8, *plan["iat_dir"])
    out += opt

    # --- заголовки секций ---
    def section(
        name: bytes, vsize: int, rva: int, raw_size: int, raw_ptr: int, chars: int
    ) -> bytes:
        """Один заголовок секции (40 байт)."""
        return struct.pack(
            "<8sIIIIIIHHI",
            name,
            vsize,
            rva,
            raw_size,
            raw_ptr,
            0,
            0,
            0,
            0,
            chars,
        )

    out += section(
        b".text",
        text_vsize,
        TEXT_RVA,
        _align(text_vsize, FILE_ALIGN),
        text_raw,
        0x60000020,
    )
    if plan["has_data"]:
        out += section(
            b".data",
            data_vsize,
            plan["data_rva"],
            _align(data_vsize, FILE_ALIGN),
            data_raw,
            0xC0000040,
        )
    out += b"\0" * (headers_size - len(out))

    # --- тела секций ---
    out += text
    out += b"\0" * (_align(len(text), FILE_ALIGN) - len(text))
    if plan["has_data"]:
        out += data_b
        out += b"\0" * (_align(len(data_b), FILE_ALIGN) - len(data_b))
    return bytes(out)
