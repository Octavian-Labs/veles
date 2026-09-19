# run_checks.ps1 — скрипт автопроверок проекта РЯП
# Форматирование, линт и тесты. Запуск: powershell -File run_checks.ps1

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m black src tests
python -m black --check src tests
python -m flake8 src tests
python -m pytest tests
