"""Тесты компилятора РАЗУМ: лексер, парсер, кодогенерация и end-to-end."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from razum.errors import RazError
from razum.lexer import tokenize
from razum.parser import parse
from razum.gen import generate
from iskra.assembler import assemble

КОРЕНЬ = Path(__file__).resolve().parent.parent


# --- лексер ------------------------------------------------------------------


def test_лексер_отступы():
    токи, _ = tokenize("функ ф():\n    верни 1\n")
    виды = [t.вид for t in токи]
    assert "ОТСТУП" in виды and "СНЯТИЕ" in виды and "НС" in виды


def test_лексер_числа():
    токи, _ = tokenize("х := 0xFF + 0b101 + 42\n")
    числа = [t.знач for t in токи if t.вид == "ЧИСЛО"]
    assert числа == [0xFF, 0b101, 42]


def test_лексер_строки_экраны():
    токи, _ = tokenize('с := "а\\nб"\n')
    стр = [t.знач for t in токи if t.вид == "СТР"]
    assert стр == ["а\nб"]


def test_лексер_комментарии():
    токи, _ = tokenize("х := 1 # коммент\n; ещё один\nу := 2\n")
    имена = [t.знач for t in токи if t.вид == "ИМЯ"]
    assert "коммент" not in имена and "ещё" not in имена


def test_лексер_табуляция_ошибка():
    with pytest.raises(RazError):
        tokenize("функ ф():\n\tверни 1\n")


# --- парсер ------------------------------------------------------------------


def test_парсер_функция():
    прог = parse("функ ф(а, б цел64) цел64:\n    верни а + б\n")
    ф = прог.decls[0]
    assert ф.имя == "ф" and len(ф.параметры) == 2
    assert ф.параметры[0].тип.вид == "цел" and ф.возвр.вид == "цел"


def test_парсер_внеш():
    прог = parse('внеш "kernel32" функ ExitProcess(код без32)\n')
    в = прог.decls[0]
    assert в.dll == "kernel32" and в.имя == "ExitProcess"
    assert в.параметры[0].тип.вид == "без" and в.параметры[0].тип.размер == 4


def test_парсер_если_а_если_иначе():
    src = (
        "функ ф(х цел64):\n    если х > 0:\n        верни 1\n"
        "    а если х == 0:\n        верни 0\n    иначе:\n        верни 2\n"
    )
    прог = parse(src)
    е = прог.decls[0].тело[0]
    assert len(е.рукава) == 2 and е.иначе is not None


def test_парсер_для_диапазон():
    прог = parse("функ ф():\n    для и в 0..10:\n        следующий\n")
    д = прог.decls[0].тело[0]
    assert д.итер.вкл is False and д.имена == ["и"]


def test_парсер_для_включительно():
    прог = parse("функ ф():\n    для и в 0..=10:\n        хватит\n")
    assert прог.decls[0].тело[0].итер.вкл is True


def test_парсер_постфикс_если():
    прог = parse("функ ф(х цел64):\n    верни 1 если х > 0\n")
    с = прог.decls[0].тело[0]
    assert type(с).__name__ == "Если"


def test_парсер_запись():
    прог = parse("запись Точка: х, у цел64\n")
    з = прог.decls[0]
    assert з.имя == "Точка" and len(з.поля) == 2


def test_парсер_переч():
    прог = parse("переч Цвет: Красный, Зелёный, Синий\n")
    п = прог.decls[0]
    assert п.элементы == ["Красный", "Зелёный", "Синий"]


def test_парсер_искра_блок():
    src = "функ ф():\n    искра:\n        ПЕР АКК, 7\n        ВОЗВРАТ\n"
    прог = parse(src)
    и = прог.decls[0].тело[0]
    assert "ПЕР АКК, 7" in и.строки


def test_парсер_ошибка_синтаксиса():
    with pytest.raises(RazError):
        parse("функ ф(:\n")


# --- генерация ----------------------------------------------------------------


def test_ген_простая_функция():
    искра = generate(parse("функ главная() цел64:\n    верни 7\n"))
    assert "ф_главная:" in искра and "старт:" in искра
    assert "ВХОД старт" in искра


def test_ген_цикл_для():
    искра = generate(parse("функ главная():\n    для и в 0..5:\n        хватит\n"))
    assert "УВЕЛ" in искра and "БОЛРАВ" in искра


def test_ген_импорты():
    src = 'внеш "kernel32" функ ExitProcess(код без32)\nфунк главная():\n    верни 0\n'
    искра = generate(parse(src))
    assert 'ИМПОРТ "kernel32"' in искра and "ExitProcess" in искра


def test_ген_строка_в_данные():
    искра = generate(parse('функ главная():\n    с := "текст"\n'))
    assert "СЕКЦИЯ данные" in искра and 'БАЙТ "текст", 0' in искра


def test_ген_нет_главной():
    with pytest.raises(RazError):
        generate(parse("функ ф():\n    верни 0\n"))


# --- end-to-end ----------------------------------------------------------------


def test_e2e_компиляция_в_pe():
    """Полный путь: .раз -> .иск -> PE64 байты."""
    src = (КОРЕНЬ / "examples" / "привет.раз").read_text(encoding="utf-8")
    искра = generate(parse(src))
    бин = assemble(искра, target="windows")
    assert бин[:2] == b"MZ"


def test_e2e_запуск_привет():
    """Собираем и реально запускаем exe — только на Windows."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    src = (КОРЕНЬ / "examples" / "привет.раз").read_text(encoding="utf-8")
    бин = assemble(generate(parse(src)), target="windows")
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(бин)
        exe = f.name
    р = subprocess.run([exe], capture_output=True)
    assert р.returncode == 0
    assert "Привет" in р.stdout.decode("utf-8", errors="replace")


def test_e2e_вычисления_код_выхода():
    """сумма 1..10 == 55 — проверяем через код выхода."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    src = (КОРЕНЬ / "examples" / "вычисления.раз").read_text(encoding="utf-8")
    бин = assemble(generate(parse(src)), target="windows")
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(бин)
        exe = f.name
    р = subprocess.run([exe], capture_output=True)
    assert р.returncode == 55


def test_e2e_linux_elf():
    """Тот же исходник — цель linux: собирается в ELF64."""
    src = (КОРЕНЬ / "examples" / "выход_linux.раз").read_text(encoding="utf-8")
    бин = assemble(generate(parse(src), target="linux"), target="linux")
    assert бин[:4] == b"\x7fELF"
