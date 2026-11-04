param([ValidateRange(1, 65535)][int]$Port = 8765, [switch]$Refresh)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. Install it and select it before creating .venv.' }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    $Refresh = [switch]::new($true)
}
& $projectPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'The existing .venv uses an unsupported Python. Stop the app, rename .venv, then create a new .venv with Python 3.11+ and rerun this script. Your .workbench data stays in place.'
}
$packageCheck = @'
import sys
try:
    import tomllib
    from pathlib import Path
    from reachscope_workbench import __version__
    from reachscope_workbench.api.app import create_app
    with (Path(sys.argv[1]) / 'pyproject.toml').open('rb') as source:
        expected = tomllib.load(source)['project']['version']
    raise SystemExit(0 if __version__ == expected else 1)
except (ImportError, OSError, ValueError, KeyError):
    raise SystemExit(1)
'@
& $projectPython -c $packageCheck $PSScriptRoot
if ($Refresh -or $LASTEXITCODE -ne 0) {
    Write-Host 'Installing the current ReachScope version into the local environment...'
    & $projectPython -m pip install .
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Check the pip output.' }
}
if (-not $env:APKTOOL_JAR) {
    $decoderDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools'
    if (Test-Path -LiteralPath $decoderDir) {
        $decoder = Get-ChildItem -LiteralPath $decoderDir -Filter 'apktool*.jar' -File | Sort-Object Name -Descending | Select-Object -First 1
        if ($decoder) { $env:APKTOOL_JAR = $decoder.FullName }
    }
}
& $projectPython -m reachscope_workbench doctor --data (Join-Path $PSScriptRoot '.workbench')
if ($LASTEXITCODE -ne 0) { throw 'Startup checks failed. Resolve the blocked items above before starting.' }
Write-Host "ReachScope Workbench: http://127.0.0.1:$Port/#/guide"
Write-Host 'Press Ctrl+C to stop. Evidence and job history are stored locally.'
& $projectPython -m reachscope_workbench serve --port $Port --data (Join-Path $PSScriptRoot '.workbench')
