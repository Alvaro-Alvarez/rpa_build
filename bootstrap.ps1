param(
    [string]$VenvPath = ".venv",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

function Step($message) {
    Write-Host "[setup] $message"
}

Step "Validando Python"
& $PythonExe --version | Out-Null

if (-not (Test-Path -LiteralPath $VenvPath)) {
    Step "Creando entorno virtual en '$VenvPath'"
    & $PythonExe -m venv $VenvPath
} else {
    Step "El entorno virtual ya existe en '$VenvPath'"
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "No se encontro el interprete del entorno virtual en '$venvPython'."
}

Step "Actualizando pip"
& $venvPython -m pip install --upgrade pip

Step "Instalando dependencias desde requirements.txt"
& $venvPython -m pip install -r requirements.txt

Step "Verificando sintaxis base del proyecto"
& $venvPython _check_syntax.py

Step "Bootstrap finalizado"
Write-Host ""
Write-Host "Para activar el entorno en PowerShell:"
Write-Host ".\$VenvPath\Scripts\Activate.ps1"
