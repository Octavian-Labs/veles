/* Подсветчик синтаксиса РАЗУМА: токенизатор → HTML-спаны.
   Классы: t-kw t-type t-str t-num t-com t-lit t-mnem t-fn t-depr t-op */
(function () {
    "use strict";

    var KW = ("функ верни если иначе пока для в вечно выбор хватит следующий " +
        "отложи взять внеш искра запись переч конст тип введи открыто скрыто " +
        "как и или не а новый освободи размер выдели смести").split(" ");
    var KW_SET = {};
    KW.forEach(function (w) { KW_SET[w] = true; });

    var LIT_SET = { "да": 1, "нет": 1, "пусто": 1 };
    var TYPE_SET = { "лог": 1, "сим": 1, "стр": 1, "размер": 1, "смещение": 1 };
    var TYPE_RE = /^(цел|нат|вещ|век)\.(старт|шаг|шагм|рост|верх|пик)$/;
    var DEPR_RE = /^(цел|без)(8|16|32|64|128)$|^бул$|^д(32|64)$/;
    var MNEM_RE = /^[A-ZА-ЯЁ0-9_.]{2,}$/;            /* ПЕР, ВЫЗОВ, АКК, БАЙТ… */
    var ID_START = /[A-Za-zА-Яа-яЁё_]/;
    var ID_CONT = /[A-Za-zА-Яа-яЁё0-9_]/;
    var NUM_RE = /^0[xX][0-9a-fA-F_]+|^0[bB][01_]+|^\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d[\d_]*)?/;
    var OPS2 = ["..=", "..", "<<", ">>", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="];
    var OPS1 = "+-*/%=<>&|^!()[]{},:.?";

    function esc(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function classifyIdent(word, rest) {
        if (TYPE_RE.test(word)) return "t-type";
        if (!/\./.test(word)) {
            if (KW_SET[word]) return "t-kw";
            if (LIT_SET[word]) return "t-lit";
            if (TYPE_SET[word]) return "t-type";
            if (DEPR_RE.test(word)) return "t-depr";
            if (MNEM_RE.test(word)) return "t-mnem";
            if (/^\s*\(/.test(rest)) return "t-fn";   /* вызов функции */
        }
        return null;
    }

    function highlight(src) {
        var out = "", i = 0, n = src.length;
        function emit(cls, s) {
            out += cls ? '<span class="' + cls + '">' + esc(s) + "</span>" : esc(s);
        }
        while (i < n) {
            var c = src[i], j, m;

            /* пробелы и переводы строк */
            if (c === " " || c === "\t" || c === "\n" || c === "\r") {
                j = i;
                while (j < n && /[ \t\n\r]/.test(src[j])) j++;
                emit(null, src.slice(i, j)); i = j; continue;
            }
            /* комментарии: '#' и ';' до конца строки */
            if (c === "#" || c === ";") {
                j = src.indexOf("\n", i);
                if (j < 0) j = n;
                emit("t-com", src.slice(i, j)); i = j; continue;
            }
            /* строковый литерал */
            if (c === '"') {
                j = i + 1;
                while (j < n && src[j] !== '"') {
                    if (src[j] === "\\") j++;
                    j++;
                }
                j = Math.min(j + 1, n);
                emit("t-str", src.slice(i, j)); i = j; continue;
            }
            /* числа */
            if (/[0-9]/.test(c)) {
                m = src.slice(i).match(NUM_RE);
                if (m) { emit("t-num", m[0]); i += m[0].length; continue; }
            }
            /* идентификаторы и цепочки a.b.c */
            if (ID_START.test(c)) {
                j = i + 1;
                while (j < n && ID_CONT.test(src[j])) j++;
                while (src[j] === "." && j + 1 < n && ID_START.test(src[j + 1])) {
                    j += 2;
                    while (j < n && ID_CONT.test(src[j])) j++;
                }
                var word = src.slice(i, j);
                emit(classifyIdent(word, src.slice(j)), word); i = j; continue;
            }
            /* двух- и трёхсимвольные операторы */
            var two = src.substr(i, 3), matched = false;
            for (var k = 0; k < OPS2.length; k++) {
                if (two.slice(0, OPS2[k].length) === OPS2[k]) {
                    emit("t-op", OPS2[k]); i += OPS2[k].length; matched = true; break;
                }
            }
            if (matched) continue;
            if (OPS1.indexOf(c) >= 0) { emit("t-op", c); i++; continue; }
            emit(null, c); i++;
        }
        return out;
    }

    /* Подсветить все <pre class="razum"> внутри корня */
    function highlightAll(root) {
        var nodes = (root || document).querySelectorAll("pre.razum code");
        for (var k = 0; k < nodes.length; k++) {
            nodes[k].innerHTML = highlight(nodes[k].textContent);
        }
    }

    window.RazumHL = { highlight: highlight, highlightAll: highlightAll };
})();
