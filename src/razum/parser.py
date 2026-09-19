"""Парсер РАЗУМА: поток токенов -> AST.

Грамматика — docs/04-разум.md. Блоки — через отступы, как в Яре.
Группы параметров — как в Go: `а, б цел64` (последний идентификатор —
тип всей группы).
"""

from __future__ import annotations

from .errors import RazError
from . import nodes as N
from .lexer import tokenize

_СРАВ = {"==", "!=", "<", "<=", ">", ">="}
_ТИПЫ = set(N.ПРИМИТИВЫ)


class Парсер:
    """Рекурсивный спуск."""

    def __init__(self, токи: list, src_lines: list):
        self.т = токи
        self.i = 0
        self.src = src_lines

    # --- служебные ----------------------------------------------------------

    def ток(self, k=0):
        return self.т[self.i + k]

    def далее(self):
        t = self.т[self.i]
        self.i += 1
        return t

    def это(self, знач):
        return self.ток().знач == знач

    def жди(self, знач):
        t = self.ток()
        if t.знач != знач:
            raise RazError(f"ожидалось {знач!r}, получено {t.знач!r}", t.строка)
        self.i += 1
        return t

    def жди_имя(self):
        t = self.ток()
        if t.вид != "ИМЯ":
            raise RazError(f"ожидалось имя, получено {t.знач!r}", t.строка)
        self.i += 1
        return t.знач

    def жди_слово(self, слово):
        t = self.ток()
        if t.вид != "ИМЯ" or t.знач != слово:
            raise RazError(f"ожидалось «{слово}», получено {t.знач!r}", t.строка)
        self.i += 1

    def жди_вид(self, вид):
        t = self.ток()
        if t.вид != вид:
            raise RazError(f"ожидался {вид}, получено {t.вид}", t.строка)
        self.i += 1

    def пропусти_нс(self):
        while self.ток().вид == "НС":
            self.i += 1

    def _конец_строки(self):
        if self.ток().вид not in ("НС", "КФ", "СНЯТИЕ"):
            raise RazError(
                f"лишний текст в конце строки: {self.ток().знач!r}",
                self.ток().строка,
            )

    # --- типы ----------------------------------------------------------------

    def тип(self) -> N.Тип:
        t = self.ток()
        if self.это("*"):
            self.далее()
            return N.указ(self.тип())
        if self.это("["):
            self.далее()
            self.жди("]")
            return N.срез(self.тип())
        if self.это("функ"):
            self.далее()
            self.жди("(")
            парамы = []
            if not self.это(")"):
                while True:
                    парамы.append(self.тип())
                    if not self.это(","):
                        break
                    self.далее()
            self.жди(")")
            возвр = self.тип() if not self.это(":") else N.ПУСТО
            return N.функ_тип(парамы, возвр)
        if t.вид == "ИМЯ":
            self.далее()
            base = N.ПРИМИТИВЫ.get(t.знач) or N.запись(t.знач)
        else:
            raise RazError(f"ожидался тип, получено {t.знач!r}", t.строка)
        # постфиксные [N] и []
        while self.это("["):
            self.далее()
            if self.это("]"):
                self.далее()
                base = N.срез(base)
            else:
                n = self.ток()
                if n.вид != "ЧИСЛО":
                    raise RazError("длина массива — число", n.строка)
                self.далее()
                self.жди("]")
                base = N.масс(base, n.знач)
        return base

    # --- блоки ----------------------------------------------------------------

    def блок(self) -> list:
        """Блок после ':' — инлайн на той же строке или отступный."""
        self.жди(":")
        if self.ток().вид != "НС":
            return [self.оператор()]
        self.пропусти_нс()
        if self.ток().вид != "ОТСТУП":
            raise RazError("ожидался отступный блок", self.ток().строка)
        self.далее()
        тело = []
        while self.ток().вид not in ("СНЯТИЕ", "КФ"):
            if self.ток().вид == "НС":
                self.далее()
                continue
            тело.append(self.оператор())
        if self.ток().вид == "СНЯТИЕ":
            self.далее()
        return тело

    # --- верхний уровень --------------------------------------------------------

    def программа(self) -> N.Программа:
        decls = []
        self.пропусти_нс()
        while self.ток().вид != "КФ":
            decls.append(self.объявление())
            self.пропусти_нс()
        return N.Программа(decls)

    def объявление(self):
        t = self.ток()
        line = t.строка
        if self.это("взять"):
            self.далее()
            модули = [self.жди_имя()]
            while self.это(","):
                self.далее()
                модули.append(self.жди_имя())
            self._конец_строки()
            return N.Взять(модули, line)
        if self.это("внеш"):
            self.далее()
            dll = self.ток()
            if dll.вид != "СТР":
                raise RazError("внеш: ожидалась строка с именем DLL", dll.строка)
            self.далее()
            self.жди_слово("функ")
            имя = self.жди_имя()
            парамы = self._параметры()
            возвр = self._тип_возврата()
            self._конец_строки()
            return N.Внеш(dll.знач, имя, парамы, возвр, line)
        if self.это("функ"):
            self.далее()
            приёмник = None
            if self.это("("):
                # метод: функ (т Точка) имя(...)
                self.далее()
                приёмник = N.Парам(self.жди_имя(), self.тип())
                self.жди(")")
            имя = self.жди_имя()
            парамы = self._параметры()
            возвр = self._тип_возврата()
            тело = self.блок()
            return N.Функ(имя, парамы, возвр, тело, line, приёмник=приёмник)
        if self.это("конст"):
            self.далее()
            имя = self.жди_имя()
            self.жди("=")
            выр = self.выражение()
            self._конец_строки()
            return N.Конст(имя, выр, line)
        if self.это("тип"):
            self.далее()
            имя = self.жди_имя()
            self.жди("=")
            тип = self.тип()
            self._конец_строки()
            return N.ТипСин(имя, тип, line)
        if self.это("запись"):
            self.далее()
            имя = self.жди_имя()
            поля = self._поля_записи()
            return N.ЗаписьДек(имя, поля, line)
        if self.это("переч"):
            self.далее()
            имя = self.жди_имя()
            элементы = self._элементы_переч()
            return N.Переч(имя, элементы, line)
        raise RazError(f"ожидалось объявление, получено {t.знач!r}", line)

    def _параметры(self) -> list:
        """Параметры: `имя {, имя} тип` — последний идентификатор в
        comma-группе является типом (как в Go)."""
        self.жди("(")
        парамы = []
        while not self.это(")"):
            имена = [self.жди_имя()]
            тип = None
            while self.это(","):
                nxt, nxt2 = self.ток(1), self.ток(2)
                if nxt.вид == "ИМЯ" and nxt2.знач == ",":
                    self.далее()
                    имена.append(self.жди_имя())
                    continue
                if nxt.вид == "ИМЯ" and (nxt2.вид == "ИМЯ" or nxt2.знач in ("*", "[")):
                    self.далее()
                    имена.append(self.жди_имя())
                    continue
                # за запятой — тип группы
                self.далее()
                тип = self.тип()
                break
            if тип is None:
                if self.ток().вид != "ИМЯ" and not self.это("*") and not self.это("["):
                    raise RazError(
                        f"параметру {имена[-1]!r} не указан тип",
                        self.ток().строка,
                    )
                тип = self.тип()
            for имя in имена:
                парамы.append(N.Парам(имя, тип))
            if not self.это(","):
                break
            self.далее()
        self.жди(")")
        return парамы

    def _тип_возврата(self) -> N.Тип:
        """Возвращаемый тип: всё между ')' и ':'/концом строки."""
        if self.это(":") or self.ток().вид in ("НС", "КФ"):
            return N.ПУСТО
        return self.тип()

    def _поля_записи(self) -> list:
        """Поля записи: `запись Т: х, у цел64` или отступный блок."""
        поля = []
        if self.это(":"):
            self.далее()
            if self.ток().вид == "НС":
                self.пропусти_нс()
                self.жди_вид("ОТСТУП")
                while self.ток().вид != "СНЯТИЕ":
                    if self.ток().вид == "НС":
                        self.далее()
                        continue
                    поля += self._строка_полей()
                self.жди_вид("СНЯТИЕ")
            else:
                поля += self._строка_полей()
        return поля

    def _строка_полей(self) -> list:
        имена = [self.жди_имя()]
        while self.это(","):
            self.далее()
            имена.append(self.жди_имя())
        тип = self.тип()
        self._конец_строки()
        return [N.Парам(имя, тип) for имя in имена]

    def _элементы_переч(self) -> list:
        """Элементы перечисления: имена через запятую, можно `= значение`."""
        элементы = []
        if self.это(":"):
            self.далее()
        while True:
            имя = self.жди_имя()
            if self.это("="):
                self.далее()
                элементы.append((имя, self.выражение()))
            else:
                элементы.append(имя)
            if not self.это(","):
                break
            self.далее()
        self._конец_строки()
        return элементы

    # --- операторы -----------------------------------------------------------

    def оператор(self):
        t = self.ток()
        line = t.строка
        v = t.знач
        if v == "верни":
            self.далее()
            if self.ток().вид in ("НС", "СНЯТИЕ", "КФ"):
                return self._постфикс(N.Верни(None, line))
            return self._постфикс(N.Верни(self.выражение(), line))
        if v == "хватит":
            self.далее()
            return self._постфикс(N.Хватит(line))
        if v == "следующий":
            self.далее()
            return self._постфикс(N.Следующий(line))
        if v == "отложи":
            self.далее()
            return self._постфикс(N.Отложи(self.выражение(), line))
        if v == "если":
            return self._если(line)
        if v == "пока":
            self.далее()
            return N.Пока(self.выражение(), self.блок(), line)
        if v == "вечно":
            self.далее()
            return N.Вечно(self.блок(), line)
        if v == "для":
            return self._для(line)
        if v == "выбор":
            return self._выбор(line)
        if v == "искра":
            return self._искра(line)
        if v == "конст":
            self.далее()
            имя = self.жди_имя()
            self.жди("=")
            return N.Конст(имя, self.выражение(), line)
        # объявление / присваивание / выражение
        if t.вид == "ИМЯ" and self.ток(1).знач == ":=":
            self.далее()
            self.далее()
            return self._постфикс(N.Объявл(t.знач, None, self.выражение(), line))
        if t.вид == "ИМЯ" and self._тип_после_имени():
            имя = t.знач
            self.далее()
            тип = self.тип()
            if self.это("="):
                self.далее()
                return self._постфикс(N.Объявл(имя, тип, self.выражение(), line))
            return self._постфикс(N.Объявл(имя, тип, None, line))
        выр = self.выражение()
        if self.ток().знач in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="):
            оп = self.далее().знач
            return self._постфикс(N.Присв(выр, оп, self.выражение(), line))
        return self._постфикс(N.ВырОп(выр, line))

    def _тип_после_имени(self) -> bool:
        """«ИМЯ тип ...» — объявление с явным типом."""
        t = self.ток(1)
        if t.вид == "ИМЯ" and t.знач in _ТИПЫ:
            return True
        if t.знач in ("*", "функ"):
            return True
        if t.знач == "[":
            # «имя []Т» — срез-тип; «имя [выр]» — индексация, не объявление
            return self.ток(2).знач == "]"
        if t.вид == "ИМЯ":
            n2 = self.ток(2)
            return n2.знач in ("=", "[") or n2.вид == "НС"
        return False

    def _постфикс(self, stmt):
        """Постфиксные 'если'/'пока' после простого оператора."""
        if self.это("если"):
            line = self.далее().строка
            return N.Если([(self.выражение(), [stmt])], None, line)
        if self.это("пока"):
            line = self.далее().строка
            return N.Пока(self.выражение(), [stmt], line)
        return stmt

    def _если(self, line):
        self.далее()  # если
        рукава = [(self.выражение(), self.блок())]
        иначе = None
        while True:
            self.пропусти_нс()
            if self.это("а") and self.ток(1).знач == "если":
                self.далее()
                self.далее()
                рукава.append((self.выражение(), self.блок()))
                continue
            if self.это("иначе"):
                self.далее()
                иначе = self.блок()
            break
        return N.Если(рукава, иначе, line)

    def _для(self, line):
        self.далее()  # для
        имена = [self.жди_имя()]
        if self.это(","):
            self.далее()
            имена.append(self.жди_имя())
        self.жди_слово("в")
        return N.Для(имена, self._итератор(), self.блок(), line)

    def _итератор(self):
        """Итерируемое: диапазон a..b / a..=b или выражение."""
        a = self.выражение()
        if self.это("..") or self.это("..="):
            вкл = self.далее().знач == "..="
            return N.Диап(a, self.выражение(), вкл, a.строка)
        return a

    def _выбор(self, line):
        self.далее()  # выбор
        выр = self.выражение()
        self.жди(":")
        self.пропусти_нс()
        self.жди_вид("ОТСТУП")
        варианты = []
        иначе = None
        while self.ток().вид not in ("СНЯТИЕ", "КФ"):
            if self.ток().вид == "НС":
                self.далее()
                continue
            if self.это("иначе"):
                self.далее()
                иначе = self.блок()
                break
            образцы = [self._образец()]
            while self.это(","):
                self.далее()
                образцы.append(self._образец())
            варианты.append((образцы, self.блок()))
        if self.ток().вид == "СНЯТИЕ":
            self.далее()
        return N.Выбор(выр, варианты, иначе, line)

    def _образец(self):
        a = self.выражение()
        if self.это("..") or self.это("..="):
            вкл = self.далее().знач == "..="
            return N.Диап(a, self.выражение(), вкл, a.строка)
        return a

    def _искра(self, line):
        """Блок 'искра:' — сырой текст ИСКРЫ из исходника."""
        self.далее()
        self.жди(":")
        if self.ток().вид != "НС":
            raise RazError("искра: требуется отступный блок", line)
        self.пропусти_нс()
        self.жди_вид("ОТСТУП")
        номера = []
        while self.ток().вид not in ("СНЯТИЕ", "КФ"):
            номера.append(self.ток().строка)
            while self.ток().вид not in ("НС", "КФ"):
                self.i += 1
            if self.ток().вид == "НС":
                self.i += 1
        if self.ток().вид == "СНЯТИЕ":
            self.далее()
        if not номера:
            return N.Искра([], line)
        raw = [self.src[i - 1] for i in range(min(номера), max(номера) + 1)]
        мин = min(len(s) - len(s.lstrip(" ")) for s in raw if s.strip())
        return N.Искра([s[мин:] if s.strip() else "" for s in raw], line)

    # --- выражения -------------------------------------------------------------

    def выражение(self):
        e = self._или()
        while self.это("как"):
            line = self.далее().строка
            e = N.Привед(e, self.тип(), line)
        return e

    def _или(self):
        e = self._и()
        while self.это("или"):
            line = self.далее().строка
            e = N.Бин("или", e, self._и(), line)
        return e

    def _и(self):
        e = self._сравн()
        while self.это("и"):
            line = self.далее().строка
            e = N.Бин("и", e, self._сравн(), line)
        return e

    def _сравн(self):
        e = self._бит_или()
        while True:
            t = self.ток()
            if t.знач in _СРАВ:
                оп = self.далее().знач
                e = N.Бин(оп, e, self._бит_или(), t.строка)
                continue
            if t.знач == "в" or (t.знач == "не" and self.ток(1).знач == "в"):
                line = t.строка
                neg = t.знач == "не"
                self.далее()
                if neg:
                    self.далее()
                a = self._бит_или()
                if self.это("..") or self.это("..="):
                    вкл = self.далее().знач == "..="
                    диап = N.Диап(a, self._бит_или(), вкл, line)
                    e = N.Бин("в", e, диап, line)
                    if neg:
                        e = N.Ун("не", e, line)
                else:
                    raise RazError("«в» требует диапазон a..b", line)
                continue
            break
        return e

    def _бит_или(self):
        e = self._бит_иск()
        while self.это("|"):
            line = self.далее().строка
            e = N.Бин("|", e, self._бит_иск(), line)
        return e

    def _бит_иск(self):
        e = self._бит_и()
        while self.это("^"):
            line = self.далее().строка
            e = N.Бин("^", e, self._бит_и(), line)
        return e

    def _бит_и(self):
        e = self._сдвиг()
        while self.это("&"):
            line = self.далее().строка
            e = N.Бин("&", e, self._сдвиг(), line)
        return e

    def _сдвиг(self):
        e = self._сумма()
        while self.ток().знач in ("<<", ">>"):
            t = self.далее()
            e = N.Бин(t.знач, e, self._сумма(), t.строка)
        return e

    def _сумма(self):
        e = self._произв()
        while self.ток().знач in ("+", "-"):
            t = self.далее()
            e = N.Бин(t.знач, e, self._произв(), t.строка)
        return e

    def _произв(self):
        e = self._унар()
        while self.ток().знач in ("*", "/", "%"):
            t = self.далее()
            e = N.Бин(t.знач, e, self._унар(), t.строка)
        return e

    def _унар(self):
        t = self.ток()
        if t.знач == "-":
            self.далее()
            return N.Ун("-", self._унар(), t.строка)
        if t.знач in ("не", "!"):
            self.далее()
            return N.Ун("не", self._унар(), t.строка)
        if t.знач == "&":
            self.далее()
            return N.Адрес(self._унар(), t.строка)
        if t.знач == "*":
            self.далее()
            return N.Разым(self._унар(), t.строка)
        return self._постфикс_выр()

    def _постфикс_выр(self):
        e = self._атом()
        while True:
            t = self.ток()
            if t.знач == ".":
                self.далее()
                e = N.Поле(e, self.жди_имя(), t.строка)
                continue
            if t.знач == "[":
                self.далее()
                инд = self.выражение()
                if self.это("..") or self.это("..="):
                    вкл = self.далее().знач == "..="
                    диап = N.Диап(инд, self.выражение(), вкл, t.строка)
                    self.жди("]")
                    e = N.СрезДиап(e, диап, t.строка)
                    continue
                self.жди("]")
                e = N.Индекс(e, инд, t.строка)
                continue
            if t.знач == "{":
                # литерал записи/массива: Имя{...} или Имя[N]{...}
                self.далее()
                элементы = []
                if not self.это("}"):
                    while True:
                        if self.ток().вид == "ИМЯ" and self.ток(1).знач == ":":
                            имя_п = self.далее().знач
                            self.далее()
                            элементы.append((имя_п, self.выражение()))
                        else:
                            элементы.append((None, self.выражение()))
                        if not self.это(","):
                            break
                        self.далее()
                self.жди("}")
                e = N.ЛитТип(self._тип_из_атома(e, t.строка), элементы, t.строка)
                continue
            if t.знач == "(":
                self.далее()
                арги = []
                if not self.это(")"):
                    while True:
                        if self.ток().вид == "ИМЯ" and self.ток(1).знач == "=":
                            имя = self.далее().знач
                            self.далее()
                            арги.append((имя, self.выражение()))
                        else:
                            арги.append((None, self.выражение()))
                        if not self.это(","):
                            break
                        self.далее()
                self.жди(")")
                e = N.Вызов(e, арги, t.строка)
                continue
            break
        return e

    def _тип_из_атома(self, e, строка: int) -> N.Тип:
        """Превращает атом-имя в тип для литерала: Точка{..}, без8[4]{..}."""
        if isinstance(e, N.Имя):
            return N.ПРИМИТИВЫ.get(e.имя) or N.запись(e.имя)
        if isinstance(e, N.Индекс) and isinstance(e.об, N.Имя):
            base = N.ПРИМИТИВЫ.get(e.об.имя) or N.запись(e.об.имя)
            if isinstance(e.инд, N.Число):
                return N.масс(base, e.инд.знач)
        raise RazError("литерал ожидает тип: Точка{..} или Тип[N]{..}", строка)

    def _атом(self):
        t = self.ток()
        if t.вид == "ЧИСЛО":
            self.далее()
            return N.Число(t.знач, t.строка)
        if t.вид == "СТР":
            self.далее()
            return N.Строка(t.знач, t.строка)
        if t.знач == "да":
            self.далее()
            return N.Бул(True, t.строка)
        if t.знач == "нет":
            self.далее()
            return N.Бул(False, t.строка)
        if t.знач == "пусто":
            self.далее()
            return N.ПустоЛит(t.строка)
        if t.знач == "новый":
            self.далее()
            self.жди("(")
            тип = self.тип()
            self.жди(")")
            return N.Новый(тип, t.строка)
        if t.знач == "размер":
            self.далее()
            self.жди("(")
            save = self.i
            try:
                тип = self.тип()
                if self.это(")"):
                    self.далее()
                    return N.Размер(тип, t.строка)
            except RazError:
                pass
            self.i = save
            e = self.выражение()
            self.жди(")")
            return N.Размер(e, t.строка)
        if t.знач == "(":
            self.далее()
            e = self.выражение()
            self.жди(")")
            return e
        if t.вид == "ИМЯ":
            self.далее()
            return N.Имя(t.знач, t.строка)
        raise RazError(f"неожиданный токен {t.знач!r}", t.строка)


def parse(src: str) -> N.Программа:
    """Разбирает исходник РАЗУМА в AST."""
    токи, lines = tokenize(src)
    return Парсер(токи, lines).программа()
