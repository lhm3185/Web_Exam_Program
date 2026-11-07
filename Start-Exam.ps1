param(
    [ValidatePattern('^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+$')]
    [string]$StudentDomain
)

$ErrorActionPreference = 'Stop'
$examPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$examManage = Join-Path $PSScriptRoot 'manage.py'
if (-not (Test-Path -LiteralPath $examPython -PathType Leaf)) {
    throw 'Create .venv and install requirements.txt first.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $examPython -c 'import waitress'
    if ($LASTEXITCODE -ne 0) {
        throw 'Install requirements.txt before starting the server.'
    }

    & $examPython $examManage migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the exam database.' }

    if (-not $StudentDomain) {
        & $examPython $examManage serve_exam
        exit $LASTEXITCODE
    }

    $studentKey = Join-Path $PSScriptRoot '.student_secret_key'
    if (-not (Test-Path -LiteralPath $studentKey)) {
        & $examPython -c 'from pathlib import Path; from secrets import token_urlsafe; path = Path(".student_secret_key"); path.open("x", encoding="utf-8").write(token_urlsafe(48))'
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the student server key.' }
    }

    $env:EXAM_STUDENT_DOMAIN = $StudentDomain.ToLowerInvariant()
    & $examPython $examManage serve_exam --settings=config.student_settings
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
