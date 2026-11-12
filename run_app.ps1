$ErrorActionPreference = 'Stop'

function Find-Tool($Command) {
    # A terminal opened before installation can have an outdated PATH.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return $true }
    $directories = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:USERPROFILE\.local\bin",
        "$env:USERPROFILE\.cargo\bin",
        "$env:ProgramFiles\nodejs",
        "$env:LOCALAPPDATA\Programs\nodejs"
    )
    if ($Command -eq 'uv') {
        $packages = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
        if (Test-Path -LiteralPath $packages) {
            $directories += @(Get-ChildItem -LiteralPath $packages -Directory -Filter 'astral-sh.uv_*' -ErrorAction SilentlyContinue |
                Get-ChildItem -Filter 'uv.exe' -File -Recurse -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty DirectoryName -Unique)
        }
    }
    foreach ($directory in $directories) {
        if (Test-Path -LiteralPath (Join-Path $directory "$Command.exe")) {
            $env:Path = "$directory;$env:Path"
            return $true
        }
    }
    return $false
}

function Ensure-Tool($Command, $Package) {
    if (Find-Tool $Command) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Missing $Command. Install Windows App Installer (winget), then rerun this script."
    }
    Write-Host "Installing $Command..."
    & winget install --id $Package --exact --source winget
    $installExitCode = $LASTEXITCODE
    # Winget may return nonzero when the package is already up to date.
    if (Find-Tool $Command) { return }
    throw "Cannot locate $Command after winget completed (exit code $installExitCode). Repair package $Package, then rerun this script."
}

try {
    Ensure-Tool 'uv' 'astral-sh.uv'
    Ensure-Tool 'node' 'OpenJS.NodeJS.LTS'
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw 'npm is missing. Repair your Node.js installation, then rerun this script.'
    }

    Push-Location (Join-Path $PSScriptRoot 'fastapi')
    try {
        Write-Host 'Ensuring Python 3.13 is installed (compatible with dependency wheels)...'
        & uv python install 3.13
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 installation failed.' }
        Write-Host 'Checking and syncing backend dependencies with Python 3.13...'
        & uv sync --locked --python 3.13
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    } finally { Pop-Location }

    Push-Location (Join-Path $PSScriptRoot 'nextjs')
    try {
        Write-Host 'Checking frontend dependencies...'
        & npm.cmd ls --all --silent *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing frontend dependencies from package-lock.json...'
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
    } finally { Pop-Location }

    Start-Process cmd.exe -WindowStyle Hidden -WorkingDirectory (Join-Path $PSScriptRoot 'fastapi') -ArgumentList '/c', 'uv run --python 3.13 uvicorn agent_backend.main:app --reload --host 127.0.0.1 --port 8000'
    Start-Process cmd.exe -WindowStyle Hidden -WorkingDirectory (Join-Path $PSScriptRoot 'nextjs') -ArgumentList '/c', 'npm run dev -- --webpack'
    Write-Host 'Servers launched in hidden windows. Open http://localhost:3000 when the frontend is ready.'
    Write-Host 'To stop them, end the uvicorn and Node.js processes in Task Manager.'
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
