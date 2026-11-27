<#
  Unstop MCP one-line installer for Windows. No Python needed.

    irm https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/main/get.ps1 | iex

  It downloads the standalone unstop-mcp.exe from the latest GitHub release, verifies its SHA-256 checksum,
  installs it to %LOCALAPPDATA%\Programs\unstop-mcp, adds it to your PATH and starts the guided setup.

  Options (when running the file directly):
    .\get.ps1 -Version 1.2.0      install a specific version
    .\get.ps1 -NoSetup            install only
    .\get.ps1 -Uninstall          disconnect from AI apps and remove the program (your sign-in data stays)
    .\get.ps1 -Source C:\x.exe    install from a local file (offline / testing)
#>
param(
    [string]$Repo = "vinoth322006/unstop-mcp-server",
    [string]$Version = "latest",
    [string]$Source = "",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\unstop-mcp"),
    [switch]$NoSetup,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$exe = Join-Path $InstallDir "unstop-mcp.exe"

function Write-Step($m) { Write-Host "  > $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  OK $m" -ForegroundColor Green }

function Update-UserPath([string]$dir, [bool]$add) {
    # Edit HKCU\Environment directly so entries like %USERPROFILE%\bin stay unexpanded (REG_EXPAND_SZ);
    # [Environment]::SetEnvironmentVariable on Windows PowerShell 5.1 would silently turn them into plain text.
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
    try {
        $current = [string]$key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        # Work on segments but keep empty ones, so removing our entry restores the original string exactly.
        $present = @($current -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -eq $dir.TrimEnd("\") }).Count -gt 0
        if ($add -and -not $present) {
            $new = if ($current -eq "") { $dir } elseif ($current.EndsWith(";")) { "$current$dir;" } else { "$current;$dir" }
        } elseif (-not $add -and $present) {
            $new = (@($current -split ";") | Where-Object { $_.TrimEnd("\") -ne $dir.TrimEnd("\") -or $_ -eq "" }) -join ";"
        } else { $new = $current }
        if ($new -cne $current) {
            $key.SetValue("Path", $new, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            # Tell Explorer so new terminals see the change (setting any user variable broadcasts WM_SETTINGCHANGE).
            [Environment]::SetEnvironmentVariable("UNSTOP_MCP_HOME", $(if ($add) { $dir } else { $null }), "User")
        }
    } finally { $key.Close() }
    if ($add -and ($env:Path -split ";") -notcontains $dir) { $env:Path = "$env:Path;$dir" }
}

if ($Uninstall) {
    Write-Host "`nRemoving Unstop MCP..." -ForegroundColor Cyan
    if (Test-Path $exe) { & $exe connect all --remove }
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    Update-UserPath $InstallDir $false
    Write-Ok "Removed. Your sign-in data is in $HOME\.unstop-mcp (delete it to sign out completely)."
    return
}

Write-Host "`nInstalling Unstop MCP" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("unstop-mcp-" + [guid]::NewGuid().ToString("N") + ".exe")

if ($Source) {
    Write-Step "Using local file $Source"
    Copy-Item $Source $tmp
} else {
    $api = if ($Version -eq "latest") { "https://api.github.com/repos/$Repo/releases/latest" }
           else { "https://api.github.com/repos/$Repo/releases/tags/v$($Version.TrimStart('v'))" }
    Write-Step "Finding the release on GitHub"
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "unstop-mcp-installer" }
    $asset = $release.assets | Where-Object { $_.name -like "unstop-mcp-*-windows-x64.exe" } | Select-Object -First 1
    if (-not $asset) { throw "No Windows build found in release $($release.tag_name)." }
    Write-Step "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing

    $sums = $release.assets | Where-Object { $_.name -eq "SHA256SUMS.txt" } | Select-Object -First 1
    if ($sums) {
        $expected = ((Invoke-WebRequest -Uri $sums.browser_download_url -UseBasicParsing).Content -split "`n" |
            Where-Object { $_ -match [regex]::Escape($asset.name) } | ForEach-Object { ($_ -split "\s+")[0] }) | Select-Object -First 1
        $actual = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
        if (-not $expected -or $actual -ne $expected.ToLower()) {
            Remove-Item $tmp -Force
            throw "Checksum mismatch for $($asset.name). The download was not installed."
        }
        Write-Ok "Checksum verified"
    } else {
        Write-Host "  ! No checksum file in this release; skipping verification." -ForegroundColor Yellow
    }
}

# Replacing a running exe: Windows allows renaming it, so move the old one aside first.
if (Test-Path $exe) {
    $old = "$exe.old"
    Remove-Item $old -Force -ErrorAction SilentlyContinue
    Rename-Item $exe $old -ErrorAction SilentlyContinue
}
Move-Item $tmp $exe -Force
Remove-Item "$exe.old" -Force -ErrorAction SilentlyContinue
Update-UserPath $InstallDir $true
Write-Ok ("Installed " + (& $exe --version) + " to $InstallDir")

if (-not $NoSetup) { & $exe setup }
else { Write-Host "`n  Next: run  unstop-mcp setup  (open a new terminal first so PATH updates)." }
