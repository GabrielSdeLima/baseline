# Starts the Baseline API with the auto-sync scheduler enabled.
#
# Can be run manually:
#     powershell -ExecutionPolicy Bypass -File scripts\start_api.ps1
#
# Or registered with Task Scheduler (see register_autostart.ps1) so the API
# boots automatically when you log in to Windows.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Activate venv if present
$Activate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $Activate) {
    . $Activate
}

# Load .env into the process environment (simple KEY=VALUE parser; ignores
# comments and blank lines).  pydantic-settings ALSO reads .env, but loading
# here lets sync_garmin.py subprocesses inherit the same env.
$EnvFile = Join-Path $RepoRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") {
            $name = $matches[1]
            $value = $matches[2].Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# Blocks.  Task Scheduler runs this as a hidden background process.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
