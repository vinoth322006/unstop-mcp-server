# Unstop MCP installer for Windows.
# Run from the project folder:   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Find-Python {
    foreach ($cmd in @("py -3.12", "py -3.11", "python")) {
        $parts = $cmd.Split(" ")
        try {
            $ver = & $parts[0] $parts[1..($parts.Length - 1)] -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.11") { return ,$parts }
        } catch { }
    }
    return $null
}

Write-Host "`nInstalling Unstop MCP..." -ForegroundColor Cyan
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and run this again." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    & $py[0] $py[1..($py.Length - 1)] -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet .
Write-Host "Installed." -ForegroundColor Green

& .\.venv\Scripts\unstop-mcp.exe setup
