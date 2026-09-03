# ============================================================================
# scripts/run_checks.ps1 -- PowerShell wrapper for ``run_checks.py``
# ============================================================================
#
# This is a thin wrapper so Windows developers can run::
#
#     .\scripts\run_checks.ps1
#
# instead of having to remember to invoke the interpreter explicitly.  It
# forwards every argument to the Python entry point and propagates its
# exit code, so ``$LASTEXITCODE`` after a run reflects the real result
# of the underlying checks (0 = pass, 1 = at least one check failed).
#
# Cross-platform note:
#   * The wrapper uses the same Python the user invoked when they ran
#     ``pwsh`` (we look up ``python`` on ``$env:PATH``).  If you have
#     multiple interpreters, activate the right venv first.
#   * On non-Windows shells the file is harmless -- it's just a
#     ``.ps1`` text file and won't be executed automatically.
# ============================================================================

$ErrorActionPreference = "Stop"

# Resolve the script directory regardless of how the user invoked us
# (absolute path, relative path, or ".\scripts\run_checks.ps1").
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$EntryPoint = Join-Path $ScriptDir "run_checks.py"

if (-not (Test-Path $EntryPoint)) {
    Write-Error "run_checks.py not found next to run_checks.ps1 ($EntryPoint)."
    exit 1
}

# Prefer the active venv's Python if there is one, otherwise fall back
# to whatever ``python`` is on the PATH.
$Python = $null
if ($env:VIRTUAL_ENV) {
    $candidate = Join-Path $env:VIRTUAL_ENV "Scripts/python.exe"
    if (Test-Path $candidate) { $Python = $candidate }
}
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
    Write-Error "Python is not on PATH. Activate a virtualenv or install Python 3.11+."
    exit 1
}

Write-Host "[run_checks.ps1] Using Python: $Python"
Write-Host "[run_checks.ps1] Project root: $ProjectRoot"
Write-Host ""

# Set CWD to the project root so ``run_checks.py`` finds ``tests/`` and
# ``scripts/`` exactly the same way as on the command line.
Push-Location $ProjectRoot
try {
    # Force UTF-8 I/O so the embedded interpreter doesn't choke on the
    # ``\u2705`` / ``\u274c`` summary markers when its stdout is being
    # pipelined through PowerShell (which would otherwise re-encode to
    # CP1252 and surface a traceback in the pipe).
    $env:PYTHONIOENCODING = "utf-8"
    & $Python $EntryPoint @args
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[run_checks.ps1] run_checks.py exited with code $exitCode." -ForegroundColor Red
} else {
    Write-Host ""
    Write-Host "[run_checks.ps1] OK." -ForegroundColor Green
}

exit $exitCode
