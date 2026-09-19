"""Ошибки компилятора РАЗУМ."""


class RazError(Exception):
    """Ошибка компиляции с привязкой к строке исходника."""

    def __init__(self, msg: str, line: int | None = None):
        self.line = line
        super().__init__(f"строка {line}: {msg}" if line else msg)
