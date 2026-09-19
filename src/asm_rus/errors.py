"""Ошибки ассемблера с привязкой к строке исходника."""


class AsmError(Exception):
    """Ошибка ассемблирования с номером строки."""

    def __init__(self, message: str, line: int | None = None):
        """Создаёт ошибку; при наличии номера строки добавляет его в текст."""
        self.line = line
        if line is not None:
            super().__init__(f"строка {line}: {message}")
        else:
            super().__init__(message)
