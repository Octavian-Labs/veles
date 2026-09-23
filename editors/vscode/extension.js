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
