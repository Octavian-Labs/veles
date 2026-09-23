/* Движок проектного курса: шаги, растущий файл с подсветкой новых строк,
   проверки, прогресс в localStorage, песочница с живой подсветкой. */
(function () {
    "use strict";

    var STORE_KEY = "veles-course-progress";
    var content = document.getElementById("content");
    var list = document.getElementById("lesson-list");

    function esc(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    /* ── прогресс ─────────────────────────────────── */
    function loadProgress() {
        try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
        catch (e) { return {}; }
    }
    var progress = loadProgress();
    function saveProgress() {
        localStorage.setItem(STORE_KEY, JSON.stringify(progress));
    }
    function doneCount() {
        var n = 0;
        STEPS.forEach(function (s) { if (progress[s.id]) n++; });
        return n;
    }
    function refreshChrome() {
        var pct = Math.round(doneCount() / STEPS.length * 100);
        document.getElementById("progress-bar").style.width = pct + "%";
        var cur = location.hash.slice(1) || "s0";
        var links = list.querySelectorAll("a");
        for (var i = 0; i < links.length; i++) {
            var id = links[i].getAttribute("href").slice(1);
            links[i].classList.toggle("done", !!progress[id]);
            links[i].classList.toggle("cur", id === cur);
        }
    }

    /* ── боковой список шагов ─────────────────────── */
    function buildList() {
        var html = "";
        STEPS.forEach(function (s, i) {
            html += '<a href="#' + s.id + '"><span class="dot"></span>' +
                '<span class="snum">' + i + '</span>' + esc(s.title) + "</a>";
        });
        html += '<a href="#sandbox" class="sand"><span class="dot"></span>Песочница</a>';
        list.innerHTML = html;
    }

    /* ── сборка исходника шага ────────────────────── */
    /* Полный файл = кусочки в порядке ORDER; новые — по newIdx. */
    function stepSource(step) {
        var src = "", marks = {}, off = 0;
        ORDER.forEach(function (name, ci) {
            var chunk = step.chunks[name] || "";
            var lines = chunk === "" ? 0
                : chunk.split("\n").length - (chunk.endsWith("\n") ? 1 : 0);
            if (step.newIdx && step.newIdx.indexOf(ci) >= 0)
                for (var l = 0; l < lines; l++) marks[off + l] = 1;
            src += chunk;
            off += lines;
        });
        return { src: src.replace(/\n$/, ""), marks: marks };
    }

    function newChunkText(step) {
        var t = "";
        (step.newIdx || []).forEach(function (ci) {
            t += step.chunks[ORDER[ci]] || "";
        });
        return t.replace(/\n$/, "");
    }

    /* файл целиком: подсветка + зелёные новые строки */
    function fileViewHTML(src, marks) {
        var lines = RazumHL.highlight(src).split("\n");
        var body = lines.map(function (l, i) {
            return '<div class="ln' + (marks[i] ? " ln-new" : "") + '">' +
                (l === "" ? "&nbsp;" : l) + "</div>";
        }).join("");
        return '<pre class="razum lines">' + body + "</pre>";
    }

    /* ── рендер частей ────────────────────────────── */
    function renderPart(part, idx) {
        switch (part.t) {
        case "h":    return "<h2>" + part.text + "</h2>";
        case "p":    return "<p>" + part.html + "</p>";
        case "list": return "<ul><li>" + part.items.join("</li><li>") + "</li></ul>";
        case "note":
            return '<div class="note ' + (part.kind || "") + '">' +
                '<span class="nt">' +
                (part.kind === "warn" ? "Важно" : part.kind === "ok" ? "Итог" : "Заметка") +
                "</span>" + part.html + "</div>";
        case "out":
            return '<div class="term"><span class="out">' +
                esc(part.text).replace(/\n/g, "<br>") + "</span></div>";
        case "quiz":
            var opts = "";
            part.options.forEach(function (o, i) {
                opts += '<button class="opt" data-q="' + idx + '" data-o="' + i + '">' +
                    esc(o) + "</button>";
            });
            return '<div class="quiz" id="quiz-' + idx + '">' +
                '<div class="qq">' + part.q + "</div>" + opts +
                '<div class="why">' + part.why + "</div></div>";
        }
        return "";
    }

    /* ── шаг ──────────────────────────────────────── */
    function renderStep(step, pos) {
        var html = "<h1><span class=\"num\">Шаг " + pos + "</span> " +
            esc(step.title) + "</h1><p class=\"goal\">" + esc(step.goal) + "</p>";

        /* код шага — сразу после цели: что добавить и файл целиком */
        if (step.chunks) {
            var s = stepSource(step);
            html += '<div class="codewrap"><div class="cap">' +
                '<span class="fname">' + esc(step.newLabel || "Новый код") + "</span>" +
                '<span class="sp"></span></div>' +
                '<pre class="razum"><code>' +
                RazumHL.highlight(newChunkText(step)) + "</code></pre></div>";
            html += '<div class="codewrap"><div class="cap">' +
                '<span class="fname">викторина.раз</span>' +
                '<span class="legend">— зелёным: новое</span><span class="sp"></span>' +
                '<button class="copy" id="copy-full">Копировать файл</button></div>' +
                fileViewHTML(s.src, s.marks) + "</div>";
        }

        step.parts.forEach(function (p, i) { html += renderPart(p, i); });

        html += '<button class="btn-done' + (progress[step.id] ? " done" : "") +
            '" id="btn-done">' +
            (progress[step.id] ? "✓ Шаг пройден" : "Шаг сделан") + "</button>";

        html += '<div class="lesson-nav">';
        html += pos > 0
            ? '<a href="#' + STEPS[pos - 1].id + '">← ' + esc(STEPS[pos - 1].title) + "</a>"
            : "<span></span>";
        html += pos < STEPS.length - 1
            ? '<a href="#' + STEPS[pos + 1].id + '">' + esc(STEPS[pos + 1].title) + " →</a>"
            : '<a href="#sandbox">Песочница →</a>';
        html += "</div>";

        content.innerHTML = html;

        var copyBtn = document.getElementById("copy-full");
        if (copyBtn) {
            copyBtn.addEventListener("click", function () {
                navigator.clipboard.writeText(stepSource(step).src).then(function () {
                    copyBtn.textContent = "Скопировано";
                    setTimeout(function () {
                        copyBtn.textContent = "Копировать файл";
                    }, 1200);
                });
            });
        }
        content.querySelectorAll(".quiz .opt").forEach(function (b) {
            b.addEventListener("click", function () {
                var qi = +b.getAttribute("data-q");
                var oi = +b.getAttribute("data-o");
                var quiz = step.parts[qi];
                var box = document.getElementById("quiz-" + qi);
                if (box.classList.contains("solved")) return;
                if (oi === quiz.answer) {
                    b.classList.add("right");
                    box.classList.add("solved");
                } else {
                    b.classList.add("wrong");
                    setTimeout(function () { b.classList.remove("wrong"); }, 700);
                }
            });
        });
        var done = document.getElementById("btn-done");
        done.addEventListener("click", function () {
            if (progress[step.id]) delete progress[step.id];
            else progress[step.id] = true;
            saveProgress();
            done.classList.toggle("done", !!progress[step.id]);
            done.textContent = progress[step.id] ? "✓ Шаг пройден" : "Шаг сделан";
            refreshChrome();
        });
        window.scrollTo(0, 0);
    }

    /* ── песочница ────────────────────────────────── */
    function renderSandbox() {
        content.innerHTML = "<h1>Песочница</h1>" +
            '<p class="goal">Правьте код — подсветка обновляется на лету. ' +
            "Сборка — на вашей машине через разум.exe и искра.exe.</p>" +
            '<div class="editor-wrap">' +
            '<pre class="razum"><code id="hl"></code></pre>' +
            '<textarea id="ed" spellcheck="false" wrap="off"></textarea></div>' +
            '<div class="term"><span class="cmt"># сборка (PowerShell: через cmd /c):</span><br>' +
            '<span class="cmd">cmd /c "raz\\разум.exe &lt; мой.раз &gt; мой.иск"</span><br>' +
            '<span class="cmd">cmd /c "искра.exe &lt; мой.иск &gt; мой.exe"</span><br>' +
            '<span class="cmd">.\\мой.exe</span></div>' +
            "<h2>Шпаргалка</h2>" +
            '<table class="cheatsheet">' +
            "<tr><th>Конструкция</th><th>Смысл</th></tr>" +
            "<tr><td><code>имя тип = выр</code></td><td>объявление</td></tr>" +
            "<tr><td><code>введи имя = выр</code></td><td>объявление с выводом типа</td></tr>" +
            "<tr><td><code>конст ИМЯ = выр</code></td><td>константа компиляции</td></tr>" +
            "<tr><td><code>функ имя(парам тип) тип:</code></td><td>функция; блок — двоеточие + отступ</td></tr>" +
            "<tr><td><code>если/а если/иначе</code></td><td>ветвление, условие — лог</td></tr>" +
            "<tr><td><code>для и в a..b</code> / <code>a..=b</code></td><td>цикл по диапазону</td></tr>" +
            "<tr><td><code>для и, э в кол</code></td><td>индекс + элемент</td></tr>" +
            "<tr><td><code>пока усл:</code> / <code>вечно:</code></td><td>циклы</td></tr>" +
            "<tr><td><code>выбор выр: вариант:</code></td><td>ветвление по значению</td></tr>" +
            "<tr><td><code>верни / хватит / следующий / отложи</code></td><td>управление</td></tr>" +
            "<tr><td><code>*Т  &x  *p  Т[N]  []Т</code></td><td>указатель, адрес, разыменование, массив, срез</td></tr>" +
            "<tr><td><code>новый(Т) освободи(p) выдели(n)</code></td><td>куча</td></tr>" +
            "<tr><td><code>(выр как тип)</code></td><td>явное приведение; в сравнениях — скобки</td></tr>" +
            "<tr><td><code>запись / переч / тип</code></td><td>свои типы</td></tr>" +
            "<tr><td><code>взять модуль</code></td><td>импорт</td></tr>" +
            "<tr><td><code>открыто / скрыто</code></td><td>видимость</td></tr>" +
            "<tr><td><code>внеш \"dll\" функ Имя(...) тип</code></td><td>внешняя функция ОС</td></tr>" +
            "<tr><td><code>искра:</code></td><td>встроенный ассемблер</td></tr>" +
            "</table>";

        var ed = document.getElementById("ed");
        var hl = document.getElementById("hl");
        function sync() { hl.innerHTML = RazumHL.highlight(ed.value) + "\n"; }
        ed.value = localStorage.getItem("veles-sandbox") || SANDBOX_DEFAULT;
        sync();
        ed.addEventListener("input", function () {
            sync();
            localStorage.setItem("veles-sandbox", ed.value);
        });
        ed.addEventListener("scroll", function () {
            hl.parentElement.scrollTop = ed.scrollTop;
            hl.parentElement.scrollLeft = ed.scrollLeft;
        });
        ed.addEventListener("keydown", function (e) {
            if (e.key === "Tab") {
                e.preventDefault();
                var s = ed.selectionStart;
                ed.value = ed.value.slice(0, s) + "    " + ed.value.slice(ed.selectionEnd);
                ed.selectionStart = ed.selectionEnd = s + 4;
                sync();
            }
        });
        window.scrollTo(0, 0);
    }

    /* ── маршрутизация ────────────────────────────── */
    function route() {
        var id = location.hash.slice(1) || "s0";
        if (id === "sandbox") { renderSandbox(); refreshChrome(); return; }
        var pos = -1;
        STEPS.forEach(function (s, i) { if (s.id === id) pos = i; });
        if (pos < 0) { location.hash = "s0"; return; }
        renderStep(STEPS[pos], pos);
        refreshChrome();
    }

    document.getElementById("btn-reset").addEventListener("click", function () {
        if (!confirm("Сбросить прогресс и код песочницы?")) return;
        localStorage.removeItem(STORE_KEY);
        localStorage.removeItem("veles-sandbox");
        progress = {};
        route();
    });

    buildList();
    window.addEventListener("hashchange", route);
    route();
})();
