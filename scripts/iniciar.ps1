# scripts/iniciar.ps1 — Arranque local en Windows (PowerShell 5.1 o 7):
#   1) crea el entorno virtual .venv e instala las dependencias,
#   2) crea .env desde .env.example con una clave secreta nueva (solo la primera vez),
#   3) aplica las migraciones y, la primera vez, carga los datos de demostración,
#   4) revisa la configuración (python manage.py diagnostico),
#   5) abre el worker de IA en otra ventana y la web + API en esta (http://127.0.0.1:8000).
#
# Uso:  .\iniciar.bat                      (doble clic o desde la terminal)
#       .\scripts\iniciar.ps1 -Demo         (vuelve a cargar los datos de demostración)
#       .\scripts\iniciar.ps1 -IA           (instala también onnxruntime/numpy para el modelo YOLO en ONNX)
#       .\scripts\iniciar.ps1 -SinWorker    (solo la web y la API)
#       .\scripts\iniciar.ps1 -Puerto 8080
param(
    [switch]$Demo,
    [switch]$IA,
    [switch]$SinWorker,
    [int]$Puerto = 8000
)

# «Continue»: en PowerShell 5.1 los avisos que pip o Django escriben en stderr no deben cortar el script; cada paso
# revisa $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Green }
function Falla($texto) { Write-Host ""; Write-Host "ERROR: $texto" -ForegroundColor Red; Read-Host "Presiona Enter para cerrar"; exit 1 }

# ------------------------------------------------------------------ 1. Python y entorno virtual
Paso "Buscando Python 3.10 a 3.14"
$Python = $null
function Argumentos($partes) { if ($partes.Length -gt 1) { return $partes[1..($partes.Length - 1)] } else { return @() } }
foreach ($candidato in @("py -3.12", "py -3.13", "py -3.11", "py -3.10", "py -3", "python")) {
    $partes = $candidato.Split(" ")
    try {
        $extra = @(Argumentos $partes)
        $version = & $partes[0] @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) {
            $mayor, $menor = $version.Trim().Split(".")
            if ([int]$mayor -eq 3 -and [int]$menor -ge 10 -and [int]$menor -le 14) { $Python = $partes; break }
        }
    } catch { }
}
if (-not $Python) { Falla "No se encontró Python 3.10–3.14. Instálalo desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH')." }
Write-Host "    Python $version"

$VenvPy = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Paso "Creando el entorno virtual .venv"
    $extra = @(Argumentos $Python)
    & $Python[0] @extra -m venv .venv
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo crear .venv" }
}

Paso "Instalando dependencias (la primera vez tarda unos minutos)"
& $VenvPy -m pip install --upgrade pip --disable-pip-version-check -q
& $VenvPy -m pip install -r requirements.txt --disable-pip-version-check -q
if ($LASTEXITCODE -ne 0) { Falla "pip no pudo instalar requirements.txt (¿hay internet?)" }
if ($IA) {
    & $VenvPy -m pip install -r requirements-ia.txt --disable-pip-version-check -q
    if ($LASTEXITCODE -ne 0) { Falla "pip no pudo instalar requirements-ia.txt" }
}

# ------------------------------------------------------------------ 2. .env
$PrimeraVez = $false
if (-not (Test-Path ".env")) {
    Paso "Creando .env desde .env.example (con una clave secreta nueva)"
    $clave = & $VenvPy -c "import secrets; print(secrets.token_urlsafe(60))"
    $contenido = Get-Content ".env.example" -Raw -Encoding UTF8
    $contenido = $contenido -replace "(?m)^DJANGO_SECRET_KEY=.*$", "DJANGO_SECRET_KEY=$clave"
    [System.IO.File]::WriteAllText((Join-Path $Raiz ".env"), $contenido, (New-Object System.Text.UTF8Encoding($false)))
    $PrimeraVez = $true
    Write-Host "    Edita .env para conectar Supabase (DATABASE_URL), Cloudinary (CLOUDINARY_URL) y WhatsApp."
}

# ------------------------------------------------------------------ 3. base de datos
Paso "Probando la conexión a la base de datos"
& $VenvPy manage.py comprobar_bd
if ($LASTEXITCODE -ne 0) { Falla "No se pudo conectar a la base de datos. Corrige DATABASE_URL en .env según el mensaje de arriba y vuelve a ejecutar iniciar.bat (para volver a SQLite, deja DATABASE_URL vacío)." }

Paso "Aplicando migraciones"
& $VenvPy manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { Falla "migrate falló: revisa el mensaje de arriba (python manage.py diagnostico lo explica)." }

$hayUsuarios = & $VenvPy manage.py shell -v 0 --no-imports -c "from cuentas.models import User; print(int(User.objects.exists()))" 2>$null |
    Select-Object -Last 1
if ($Demo -or $PrimeraVez -or ("$hayUsuarios".Trim() -eq "0")) {
    Paso "Cargando datos de demostración (cuentas *@demo.pe, contraseña Demo2026)"
    & $VenvPy manage.py sembrar_demo
}

# ------------------------------------------------------------------ 4. diagnóstico
Paso "Revisando la configuración"
& $VenvPy manage.py diagnostico
if ($LASTEXITCODE -ne 0) { Write-Host "    Hay errores de configuración (arriba, en rojo). La web arranca igual para que puedas revisarla." -ForegroundColor Yellow }

# ------------------------------------------------------------------ 5. worker y servidor
if (-not $SinWorker) {
    Paso "Abriendo el worker de IA en otra ventana (análisis de fotos y avisos de WhatsApp)"
    $cmd = "Set-Location '$Raiz'; `$env:PYTHONUTF8='1'; `$host.UI.RawUI.WindowTitle='Riachuelo - worker IA'; & '$VenvPy' manage.py worker_ia"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd) | Out-Null
}

Paso "Iniciando la web y la API en el puerto $Puerto"
Write-Host "    Web:        http://127.0.0.1:$Puerto/"
Write-Host "    Celulares:  usa la IP que aparece abajo (misma red Wi-Fi). Si Windows pregunta por el Firewall,"
Write-Host "                permite el acceso en 'Redes privadas'."
Write-Host "    Detener:    Ctrl + C"
$host.UI.RawUI.WindowTitle = "Riachuelo - web y API"
& $VenvPy manage.py runserver "0.0.0.0:$Puerto"
