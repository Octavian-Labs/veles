"""Лексер: разбивает строки исходника на токены.

Поддерживает кириллические и латинские идентификаторы, числа
(десятичные, 0x.., 0b..), строки в кавычках и знаки препинания.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AsmError


@dataclass
class Tok:
    """Токен исходной строки."""

    kind: str  # 'id' | 'num' | 'str' | 'punct'
    val: object
    line: int


_PUNCT = set(",:[]()+-*/%$=&|^~<>")
_IDENT_START_EXTRA = set("_.")


def _is_ident_start(ch: str) -> bool:
    """Первый символ идентификатора: буква (любого алфавита), _ или точка."""
    return ch.isalpha() or ch in _IDENT_START_EXTRA


def _is_ident_char(ch: str) -> bool:
    """Символ внутри идентификатора."""
    return ch.isalnum() or ch in _IDENT_START_EXTRA


def tokenize_line(text: str, line: int) -> list[Tok]:
    """Разбивает одну строку на токены; ';' начинает комментарий."""
    toks: list[Tok] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == ";":
            break
        if ch.isspace():
            i += 1
            continue
        if ch == '"' or ch == "'":
            j = i + 1
            buf = []
            while j < n and text[j] != ch:
                if text[j] == "\\" and j + 1 < n:
                    esc = text[j + 1]
                    buf.append(
                        {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(esc, esc)
                    )
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise AsmError("незакрытая строка", line)
            toks.append(Tok("str", "".join(buf), line))
            i = j + 1
            continue
        if ch.isdigit():
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_"):
                j += 1
            word = text[i:j].replace("_", "")
            try:
                if word.lower().startswith("0x"):
                    val = int(word, 16)
                elif word.lower().startswith("0b"):
                    val = int(word, 2)
                elif word.lower().startswith("0o"):
                    val = int(word, 8)
                else:
                    val = int(word, 10)
            except ValueError:
                raise AsmError(f"некорректное число {word!r}", line)
            toks.append(Tok("num", val, line))
            i = j
            continue
        if _is_ident_start(ch):
            j = i
            while j < n and _is_ident_char(text[j]):
                j += 1
            toks.append(Tok("id", text[i:j], line))
            i = j
            continue
        if ch in "<>" and i + 1 < n and text[i + 1] == ch:
            toks.append(Tok("punct", ch + ch, line))
            i += 2
            continue
        if ch in _PUNCT:
            toks.append(Tok("punct", ch, line))
            i += 1
            continue
        raise AsmError(f"неожиданный символ {ch!r}", line)
    return toks


def tokenize(source: str) -> list[list[Tok]]:
    """Разбивает весь исходник: список строк, каждая — список токенов."""
    return [
        tokenize_line(text, no) for no, text in enumerate(source.splitlines(), start=1)
    ]
