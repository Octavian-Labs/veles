"""Лексер РАЗУМА: токены, отступы (ОТСТУП/СНЯТИЕ), строки и числа.

Виды токенов: ИМЯ, ЧИСЛО, СТР, ОП, НС (новая строка), ОТСТУП, СНЯТИЕ, КФ.
Комментарии: '#' и ';' до конца строки. Скобки ()[]{} подавляют НС.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import RazError

_МНОГО = [
    "..=",
    "<<=",
    ">>=",
    "..",
    ":=",
    "==",
    "!=",
    "<=",
    ">=",
    "<<",
    ">>",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
]
_ОДИН = set("+-*/%<>=()[]{},.:&|^!")
_ЭКРАН = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", '"': '"', "'": "'"}


@dataclass
class Ток:
    """Токен с позицией в исходнике."""

    вид: str  # ИМЯ | ЧИСЛО | СТР | ОП | НС | ОТСТУП | СНЯТИЕ | КФ
    знач: object
    строка: int
    кол: int = 0


def _число(s: str, line: int) -> int:
    """Разбирает числовой литерал: 0x/0b/0o/десятичный, '_' как разделитель."""
    t = s.replace("_", "")
    try:
        if t.lower().startswith("0x"):
            return int(t, 16)
        if t.lower().startswith("0b"):
            return int(t, 2)
        if t.lower().startswith("0o"):
            return int(t, 8)
        return int(t)
    except ValueError:
        raise RazError(f"неверное число {s!r}", line)


def tokenize(src: str) -> tuple[list, list]:
    """Токенизирует исходник. Возвращает (токены, строки_исходника)."""
    токи: list[Ток] = []
    отступы = [0]
    глубина = 0
    lines = src.split("\n")

    for no, raw in enumerate(lines, 1):
        # комментарий '#' или ';' — вне строк
        i = 0
        n = len(raw)
        while i < n:
            c = raw[i]
            if c in "\"'":
                i += 1
                while i < n and raw[i] != c:
                    i += 2 if raw[i] == "\\" else 1
            elif c in "#;":
                raw = raw[:i]
                n = len(raw)
                break
            i += 1
        if not raw.strip():
            continue

        # отступ
        колво = 0
        for ch in raw:
            if ch == " ":
                колво += 1
            elif ch == "\t":
                raise RazError("табуляция в отступе — используйте пробелы", no)
            else:
                break
        text = raw.lstrip(" ")

        if глубина == 0:
            if колво > отступы[-1]:
                отступы.append(колво)
                токи.append(Ток("ОТСТУП", колво, no))
            while колво < отступы[-1]:
                отступы.pop()
                токи.append(Ток("СНЯТИЕ", колво, no))
            if колво != отступы[-1]:
                raise RazError("неконсистентный отступ", no)

        # токены внутри строки
        j = 0
        m = len(text)
        while j < m:
            ch = text[j]
            col = j + 1
            if ch == " ":
                j += 1
                continue
            if ch.isdigit():
                k = j
                while k < m and (text[k].isalnum() or text[k] == "_"):
                    k += 1
                токи.append(Ток("ЧИСЛО", _число(text[j:k], no), no, col))
                j = k
                continue
            if ch == '"':
                k = j + 1
                buf = []
                while k < m and text[k] != '"':
                    if text[k] == "\\" and k + 1 < m:
                        e = text[k + 1]
                        if e in _ЭКРАН:
                            buf.append(_ЭКРАН[e])
                            k += 2
                            continue
                        if e == "x" and k + 3 < m:
                            buf.append(chr(int(text[k + 2 : k + 4], 16)))
                            k += 4
                            continue
                        raise RazError(f"неизвестная экранизация \\{e}", no)
                    buf.append(text[k])
                    k += 1
                if k >= m:
                    raise RazError("незакрытая строка", no)
                токи.append(Ток("СТР", "".join(buf), no, col))
                j = k + 1
                continue
            if ch == "'":
                k = j + 1
                buf = []
                while k < m and text[k] != "'":
                    if text[k] == "\\" and k + 1 < m:
                        e = text[k + 1]
                        if e in _ЭКРАН:
                            buf.append(_ЭКРАН[e])
                            k += 2
                            continue
                        if e == "x" and k + 3 < m:
                            buf.append(chr(int(text[k + 2 : k + 4], 16)))
                            k += 4
                            continue
                        raise RazError(f"неизвестная экранизация \\{e}", no)
                    buf.append(text[k])
                    k += 1
                if k >= m:
                    raise RazError("незакрытый символьный литерал", no)
                симв = "".join(buf)
                if len(симв) != 1:
                    raise RazError("символьный литерал — ровно один символ", no)
                токи.append(Ток("ЧИСЛО", ord(симв), no, col))
                j = k + 1
                continue
            if ch.isalpha() or ch == "_" or ord(ch) > 127:
                k = j
                while k < m and (
                    text[k].isalnum() or text[k] == "_" or ord(text[k]) > 127
                ):
                    k += 1
                токи.append(Ток("ИМЯ", text[j:k], no, col))
                j = k
                continue
            found = False
            for op in _МНОГО:
                if text.startswith(op, j):
                    токи.append(Ток("ОП", op, no, col))
                    j += len(op)
                    found = True
                    break
            if found:
                continue
            if ch in _ОДИН:
                токи.append(Ток("ОП", ch, no, col))
                j += 1
                continue
            raise RazError(f"неожиданный символ {ch!r}", no)

        # глубина скобок
        глубина += sum(
            1
            for t in токи
            if t.вид == "ОП" and t.строка == no and t.знач in "([{"  # noqa: E501
        )
        глубина -= sum(
            1
            for t in токи
            if t.вид == "ОП" and t.строка == no and t.знач in ")]}"  # noqa: E501
        )
        if глубина == 0:
            токи.append(Ток("НС", None, no))

    токи.append(Ток("НС", None, len(lines)))
    while len(отступы) > 1:
        отступы.pop()
        токи.append(Ток("СНЯТИЕ", 0, len(lines)))
    токи.append(Ток("КФ", None, len(lines)))
    return токи, lines
