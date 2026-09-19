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
from razum.loader import загрузить
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


def test_парсер_метод():
    прог = parse("функ (т *Точка) норма() цел64:\n    верни т.х\n")
    ф = прог.decls[0]
    assert ф.приёмник is not None and ф.приёмник.имя == "т"
    assert ф.приёмник.тип.вид == "указ"


def test_парсер_литерал_записи():
    прог = parse("функ ф():\n    т := Точка{х: 1, у: 2}\n")
    с = прог.decls[0].тело[0]
    assert type(с.выр).__name__ == "ЛитТип"
    assert с.выр.элементы[0][0] == "х"


def test_парсер_литерал_массива():
    прог = parse("функ ф():\n    а := без8[3]{1, 2, 3}\n")
    с = прог.decls[0].тело[0]
    лит = с.выр
    assert type(лит).__name__ == "ЛитТип"
    assert лит.тип.вид == "масс" and лит.тип.n == 3


def test_парсер_срез():
    прог = parse("функ ф():\n    с := arr[1..4]\n")
    с = прог.decls[0].тело[0]
    assert type(с.выр).__name__ == "СрезДиап"
    assert с.выр.диап.вкл is False


def test_парсер_тип_функция():
    прог = parse("функ ф():\n    г функ(цел64) цел64 = пусто\n")
    с = прог.decls[0].тело[0]
    assert с.тип.вид == "функ" and len(с.тип.арги) == 1


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


def test_ген_метод():
    src = (
        "запись Точка: х цел64\n"
        "функ (т *Точка) дабл() цел64:\n    верни т.х * 2\n"
        "функ главная() цел64:\n"
        "    т Точка = Точка{х: 5}\n    верни т.дабл()\n"
    )
    искра = generate(parse(src))
    assert "ф_Точка_дабл:" in искра and "ВЫЗОВ ф_Точка_дабл" in искра


def test_ген_косвенный_вызов():
    src = (
        "функ ф(а цел64) цел64:\n    верни а\n"
        "функ главная() цел64:\n"
        "    г функ(цел64) цел64 = ф\n    верни г(1)\n"
    )
    искра = generate(parse(src))
    assert "ВЫЗОВ Р11" in искра


def test_ген_искра_локали():
    src = (
        "функ главная() цел64:\n    х := 7\n"
        "    искра:\n        ПЕР АКК, х\n    верни х\n"
    )
    искра = generate(parse(src))
    assert "ПЕР АКК, [УКК-8]" in искра


def test_ген_несовместимые_типы():
    src = 'функ главная():\n    х цел64 = "текст"\n'
    with pytest.raises(RazError):
        generate(parse(src))


def test_ген_литерал_литерал_вне_диапазона():
    src = "функ главная():\n    б без8 = 999\n"
    with pytest.raises(RazError):
        generate(parse(src))


# --- модули --------------------------------------------------------------------


def test_взять_модуль(tmp_path):
    (tmp_path / "матем.раз").write_text(
        "функ квадрат(а цел64) цел64:\n    верни а * а\n", encoding="utf-8"
    )
    (tmp_path / "прога.раз").write_text(
        "взять матем\nфунк главная() цел64:\n    верни квадрат(7)\n",
        encoding="utf-8",
    )
    прог = загрузить(tmp_path / "прога.раз")
    имена = [d.имя for d in прог.decls]
    assert "квадрат" in имена and "главная" in имена
    искра = generate(прог)
    assert "ф_квадрат:" in искра


def test_взять_цикл_без_зависания(tmp_path):
    (tmp_path / "а.раз").write_text(
        "взять б\nфунк фа():\n    верни 0\n", encoding="utf-8"
    )
    (tmp_path / "б.раз").write_text(
        "взять а\nфунк фб():\n    верни 0\n", encoding="utf-8"
    )
    (tmp_path / "прога.раз").write_text(
        "взять а\nфунк главная() цел64:\n    верни 0\n", encoding="utf-8"
    )
    прог = загрузить(tmp_path / "прога.раз")
    assert any(d.имя == "фа" for d in прог.decls)


def test_взять_не_найден(tmp_path):
    (tmp_path / "прога.раз").write_text(
        "взять нету\nфунк главная():\n    верни 0\n", encoding="utf-8"
    )
    with pytest.raises(RazError):
        загрузить(tmp_path / "прога.раз")


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


def test_e2e_пробелы_код_выхода():
    """Методы, косвенные вызовы, литералы, срезы и искра-локали — код 52."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    src = (КОРЕНЬ / "examples" / "пробелы.раз").read_text(encoding="utf-8")
    бин = assemble(generate(parse(src)), target="windows")
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(бин)
        exe = f.name
    р = subprocess.run([exe], capture_output=True)
    assert р.returncode == 52


def test_e2e_stdlib_основа():
    """взять основа → печать, склейка, сравнение строк, цел_в_стр."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    прог = загрузить(КОРЕНЬ / "examples" / "основа_демо.раз")
    бин = assemble(generate(прог), target="windows")
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(бин)
        exe = f.name
    р = subprocess.run([exe], capture_output=True)
    assert р.returncode == 42
    out = р.stdout.decode("utf-8", errors="replace")
    assert "Ответ: 42" in out and "склейка работает" in out


def test_stdlib_linux_elf():
    """Та же программа на основе собирается в ELF64 (консоль.linux.раз)."""
    прог = загрузить(КОРЕНЬ / "examples" / "основа_демо.раз", target="linux")
    бин = assemble(generate(прог, target="linux"), target="linux")
    assert бин[:4] == b"\x7fELF"


def _exe_из(прог, tmp_path):
    """Собирает программу во временный exe, возвращает путь."""
    бин = assemble(generate(прог), target="windows")
    exe = tmp_path / "прог.exe"
    exe.write_bytes(бин)
    return exe


def test_e2e_stdlib_выход(tmp_path):
    """система.выход(код) завершает процесс с нужным кодом."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    прог = загрузить(КОРЕНЬ / "examples" / "выход_демо.раз")
    р = subprocess.run([str(_exe_из(прог, tmp_path))], capture_output=True)
    assert р.returncode == 7
    assert "до выхода" in р.stdout.decode("utf-8", errors="replace")


def test_e2e_stdlib_файл(tmp_path):
    """файл_запиши + файл_прочти + стр_найди + стр_число: код 42."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    прог = загрузить(КОРЕНЬ / "examples" / "файл_демо.раз")
    р = subprocess.run(
        [str(_exe_из(прог, tmp_path))], capture_output=True, cwd=tmp_path
    )
    out = р.stdout.decode("utf-8", errors="replace")
    assert р.returncode == 42
    assert "прочитано: раз два три 42" in out
    assert (tmp_path / "veles_test.txt").read_bytes() == "раз два три 42".encode(
        "utf-8"
    )


def test_e2e_stdlib_ввод(tmp_path):
    """консоль.ввод() читает весь stdin до EOF."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    прог = загрузить(КОРЕНЬ / "examples" / "ввод_демо.раз")
    данные = "тест ввода\n".encode("utf-8")
    р = subprocess.run(
        [str(_exe_из(прог, tmp_path))], capture_output=True, input=данные
    )
    assert р.returncode == 0
    assert str(len(данные)) in р.stdout.decode("utf-8", errors="replace")


def test_e2e_stdlib_список(tmp_path):
    """Список: добавление, рост ёмкости, сумма элементов — код 60."""
    if sys.platform != "win32":
        pytest.skip("запуск PE64 только на Windows")
    прог = загрузить(КОРЕНЬ / "examples" / "список_демо.раз")
    р = subprocess.run([str(_exe_из(прог, tmp_path))], capture_output=True)
    assert р.returncode == 60


def test_ген_несовместимые_указатели():
    """*Точка не присваивается *Список — указатели проверяются по базе."""
    src = (
        "запись Точка:\n"
        "    х цел64\n"
        "запись Другое:\n"
        "    у цел64\n"
        "функ главная() цел64:\n"
        "    т *Точка = новый(Точка)\n"
        "    д *Другое = т\n"
        "    верни 0\n"
    )
    with pytest.raises(RazError, match="указатели"):
        generate(parse(src))


def test_e2e_linux_elf():
    """Тот же исходник — цель linux: собирается в ELF64."""
    src = (КОРЕНЬ / "examples" / "выход_linux.раз").read_text(encoding="utf-8")
    бин = assemble(generate(parse(src), target="linux"), target="linux")
    assert бин[:4] == b"\x7fELF"
