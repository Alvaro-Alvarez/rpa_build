param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path $PythonExe)) {
    throw "No se encontro Python en '$PythonExe'."
}

Write-Host "Limpiando builds anteriores..." -ForegroundColor Cyan
if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist") { Remove-Item ".\dist" -Recurse -Force }

Write-Host "Verificando PyInstaller..." -ForegroundColor Cyan
& $PythonExe -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando PyInstaller..." -ForegroundColor Cyan
    & $PythonExe -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo instalar PyInstaller."
    }
}

Write-Host "Generando build desktop..." -ForegroundColor Cyan
& $PythonExe -m PyInstaller --clean --noconfirm .\desktop_app.spec
if ($LASTEXITCODE -ne 0) {
    throw "Fallo el build de PyInstaller."
}

$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Warning "No se encontro Inno Setup. El build desktop quedo listo en .\dist\CitySensAIBuild."
    Write-Warning "Si instalas Inno Setup 6, vuelve a ejecutar este script para generar el instalador."
    exit 0
}

Write-Host "Generando instalador..." -ForegroundColor Cyan
& $iscc .\installer\desktop_app.iss
if ($LASTEXITCODE -ne 0) {
    throw "Fallo la generacion del instalador."
}

Write-Host "Instalador generado correctamente." -ForegroundColor Green
