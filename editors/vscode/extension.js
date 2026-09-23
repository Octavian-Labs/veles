// ВЕЛЕС — живые диагностики РАЗУМА в редакторе.
// По сохранению и набору текста (с задержкой) прогоняет разум.exe над
// содержимым буфера через stdin и разбирает строки вида:
//   разум.<фаза>: <путь>: строка N(:M)?: текст      — ошибка
//   разум: предупреждение: <путь>:строка N: текст   — предупреждение
// Флаг --файл задаёт виртуальный путь stdin-исходника, поэтому ошибки
// «взять»-модулей приходят с их собственными путями и подчёркиваются
// в своих файлах.

const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');
const fs = require('fs');

const сборник = vscode.languages.createDiagnosticCollection('велес');
let статус = null;
let текПроцесс = null;
let таймер = null;

// путь к разум.exe: настройка veles.razumPath, затем raz/разум[.exe]
// в корне рабочей области, затем PATH.
function путьРазума() {
    const изНастроек = vscode.workspace.getConfiguration('veles').get('razumPath', '');
    if (изНастроек !== '') {
        return изНастроек;
    }
    const имя = process.platform === 'win32' ? 'разум.exe' : 'разум';
    for (const папка of vscode.workspace.workspaceFolders || []) {
        const кандидат = path.join(папка.uri.fsPath, 'raz', имя);
        if (fs.existsSync(кандидат)) {
            return кандидат;
        }
    }
    return имя;
}

// нормализация пути для сравнения: разум печатает путь как есть
function норм(путьФайла) {
    return path.normalize(путьФайла).toLowerCase();
}

// путь к ML-инференсу (ош_инф): настройка veles.mlPath, затем
// raz/ош_инф[.exe] в корне рабочей области, затем PATH.
function путьИнф() {
    const изНастроек = vscode.workspace.getConfiguration('veles').get('mlPath', '');
    if (изНастроек !== '') {
        return изНастроек;
    }
    const имя = process.platform === 'win32' ? 'ош_инф.exe' : 'ош_инф';
    for (const папка of vscode.workspace.workspaceFolders || []) {
        const кандидат = path.join(папка.uri.fsPath, 'raz', имя);
        if (fs.existsSync(кандидат)) {
            return кандидат;
        }
    }
    return имя;
}

// путь к обученным весам: настройка veles.mlWeights, затем raz/ош_веса.bin.
function путьВесов() {
    const изНастроек = vscode.workspace.getConfiguration('veles').get('mlWeights', '');
    if (изНастроек !== '') {
        return изНастроек;
    }
    for (const папка of vscode.workspace.workspaceFolders || []) {
        const кандидат = path.join(папка.uri.fsPath, 'raz', 'ош_веса.bin');
        if (fs.existsSync(кандидат)) {
            return кандидат;
        }
    }
    return '';
}

// Один вызов ош_инф: stdin «строка кода\nсообщение\n», stdout «вид <имя>».
// Возвращает имя класса (или пусто при отсутствии инструмента/весов).
function млУгадай(лин, сооб, готово) {
    const инф = путьИнф();
    const веса = путьВесов();
    if (веса === '' || !fs.existsSync(инф)) {
        готово('');
        return;
    }
    let вывод = '';
    const процесс = cp.spawn(инф, [веса], { cwd: path.dirname(веса) });
    процесс.stdout.on('data', (кусок) => { вывод += кусок.toString(); });
    процесс.stderr.on('data', (кусок) => { вывод += кусок.toString(); });
    процесс.on('error', () => готово(''));
    процесс.on('close', () => {
        const соот = вывод.match(/^вид (\S+)/m);
        готово(соот ? соот[1] : '');
    });
    процесс.stdin.write(лин + '\n' + сооб + '\n');
    процесс.stdin.end();
}

// строка исходника по uri и 1-based номеру (из открытого документа или диска)
function строкаФайла(uri, номер) {
    const открыт = vscode.workspace.textDocuments.find(
        (док) => норм(док.uri.fsPath) === норм(uri.fsPath));
    try {
        if (открыт) {
            return открыт.lineAt(Math.max(0, номер - 1)).text;
        }
        const строки = fs.readFileSync(uri.fsPath, 'utf8').split(/\r?\n/);
        return строки[номер - 1] || '';
    } catch (ош) {
        return '';
    }
}

// убирает префикс фазы «парсер: » — в корпусе хранился сырой текст сообщения
function чистоеСообщение(текст) {
    return текст.replace(/^[а-яёa-z]+: /, '');
}

// разбор вывода разума → диагностики по файлам
function разбериВывод(вывод, документ, каталог) {
    const поФайлам = new Map();
    const добавь = (файл, строка, столб, текст, строгость) => {
        const uri = vscode.Uri.file(файл);
        if (!поФайлам.has(uri.toString())) {
            поФайлам.set(uri.toString(), { uri: uri, список: [] });
        }
        const стр0 = Math.max(0, строка - 1);
        const ст0 = Math.max(0, столб - 1);
        const диапазон = new vscode.Range(стр0, ст0, стр0, Number.MAX_SAFE_INTEGER);
        поФайлам.get(uri.toString()).список.push(
            new vscode.Diagnostic(диапазон, текст, строгость));
    };

    for (const линия of вывод.split(/\r?\n/)) {
        // ошибки фаз: «разум.парсер: путь: строка N:M: текст»
        let соот = линия.match(/^разум\.([а-яёa-z]+): (?:(.*?): )?строка (\d+)(?::(\d+))?: (.*)$/);
        if (соот) {
            const текст = соот[5];
            const строка = parseInt(соот[3], 10);
            const столб = соот[4] ? parseInt(соот[4], 10) : 1;
            const предупр = текст.startsWith('предупреждение:');
            const строгость = предупр ? vscode.DiagnosticSeverity.Warning
                                      : vscode.DiagnosticSeverity.Error;
            let файл = соот[2];
            if (!файл || файл === './стdin.раз') {
                файл = документ.uri.fsPath;
            } else if (!path.isAbsolute(файл)) {
                файл = path.join(каталог, файл);
            }
            добавь(файл, строка, столб, соот[1] + ': ' + текст, строгость);
            continue;
        }
        // предупреждения парсера: «разум: предупреждение: путь:строка N: текст»
        соот = линия.match(/^разум: предупреждение: (?:(.*?):)?строка (\d+): (.*)$/);
        if (соот) {
            let файл = соот[1];
            if (!файл) {
                файл = документ.uri.fsPath;
            } else if (!path.isAbsolute(файл)) {
                файл = path.join(каталог, файл);
            }
            добавь(файл, parseInt(соот[2], 10), 1, соот[3],
                vscode.DiagnosticSeverity.Warning);
        }
    }
    return поФайлам;
}

function проверь(документ) {
    if (документ.languageId !== 'razum' && документ.languageId !== 'iskra') {
        return;
    }
    if (документ.languageId === 'iskra') {
        return; // пока проверяем только разум
    }
    const разум = путьРазума();
    const каталог = path.dirname(документ.uri.fsPath);
    if (текПроцесс) {
        текПроцесс.kill();
        текПроцесс = null;
    }
    const процесс = cp.spawn(разум, ['--файл', документ.uri.fsPath, '--кэш', 'выкл'],
        { cwd: каталог });
    текПроцесс = процесс;
    let вывод = '';
    процесс.stdout.on('data', (кусок) => { вывод += кусок.toString(); });
    процесс.stderr.on('data', (кусок) => { вывод += кусок.toString(); });
    процесс.on('error', () => {
        статус.text = 'ВЕЛЕС: разум не найден';
        статус.tooltip = 'Укажите путь в настройке veles.razumPath';
    });
    процесс.on('close', () => {
        if (текПроцесс === процесс) {
            текПроцесс = null;
        }
        const поФайлам = разбериВывод(вывод, документ, каталог);
        сборник.clear();
        let ошибок = 0;
        for (const { uri, список } of поФайлам.values()) {
            сборник.set(uri, список);
            ошибок += список.length;
        }
        if (ошибок === 0) {
            сборник.set(документ.uri, []);
            статус.text = 'ВЕЛЕС: чисто';
        } else {
            статус.text = 'ВЕЛЕС: ' + ошибок + ' диагн.';
            // ML-подсказка: угадываем вид первой ошибки (ош_инф, сырые веса).
            let цель = null;
            for (const { uri, список } of поФайлам.values()) {
                const первая = список.find(
                    (д) => д.severity === vscode.DiagnosticSeverity.Error);
                if (первая) {
                    цель = { uri: uri, диаг: первая, список: список };
                    break;
                }
            }
            if (цель) {
                const лин = строкаФайла(цель.uri, цель.диаг.range.start.line + 1);
                млУгадай(лин, чистоеСообщение(цель.диаг.message), (вид) => {
                    if (вид === '') {
                        return;
                    }
                    const отмечен = new vscode.Diagnostic(цель.диаг.range,
                        цель.диаг.message + '  [ML: ' + вид + ']', цель.диаг.severity);
                    отмечен.source = цель.диаг.source;
                    const новый = цель.список.map(
                        (д) => д === цель.диаг ? отмечен : д);
                    сборник.set(цель.uri, новый);
                    статус.text = статус.text.replace(/ · ML.*$/, '')
                        + ' · ML: ' + вид;
                });
            }
        }
    });
    процесс.stdin.write(документ.getText());
    процесс.stdin.end();
}

function очередь(документ) {
    if (таймер) {
        clearTimeout(таймер);
    }
    таймер = setTimeout(() => проверь(документ), 700);
}

function activate(контекст) {
    статус = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 10);
    статус.text = 'ВЕЛЕС';
    статус.tooltip = 'Диагностика разума';
    статус.show();
    контекст.subscriptions.push(статус, сборник);

    контекст.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(проверь),
        vscode.workspace.onDidSaveTextDocument(проверь),
        vscode.workspace.onDidChangeTextDocument((соб) => очередь(соб.document)),
        vscode.workspace.onDidCloseTextDocument((док) => сборник.delete(док.uri)),
        vscode.commands.registerCommand('veles.check', () => {
            const ред = vscode.window.activeTextEditor;
            if (ред) {
                проверь(ред.document);
            }
        }),
        vscode.commands.registerCommand('veles.ml', () => {
            const ред = vscode.window.activeTextEditor;
            if (!ред) {
                return;
            }
            const список = сборник.get(ред.document.uri) || [];
            if (список.length === 0) {
                vscode.window.showInformationMessage('ВЕЛЕС: диагностик нет');
                return;
            }
            const строка = ред.selection.active.line;
            const ближ = список.reduce((а, б) =>
                Math.abs(б.range.start.line - строка) <
                Math.abs(а.range.start.line - строка) ? б : а);
            const лин = ред.document.lineAt(ближ.range.start.line).text;
            млУгадай(лин, чистоеСообщение(ближ.message), (вид) => {
                if (вид === '') {
                    vscode.window.showInformationMessage(
                        'ВЕЛЕС ML: ош_инф/ош_веса.bin не найдены ' +
                        '(соберите Exp_AI_GPU/ош_инф.раз и обучите обуч_ош)');
                } else {
                    vscode.window.showInformationMessage(
                        'ВЕЛЕС ML: вид ошибки — «' + вид + '»');
                }
            });
        })
    );
    for (const док of vscode.workspace.textDocuments) {
        проверь(док);
    }
}

function deactivate() {
    if (текПроцесс) {
        текПроцесс.kill();
    }
}

module.exports = { activate, deactivate };
