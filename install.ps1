<#
.SYNOPSIS
    Voice-Command installer for Windows. Downloads voice-mcp.exe, installs Python
    dependencies, and wires the MCP entry into supported client configs.

.DESCRIPTION
    Single-script install path so an AI assistant (or a human) can take a fresh
    Windows machine from zero to talking. Detects architecture (ARM64/x64),
    grabs the matching binary from the latest GitHub release, installs the
    Python listening-server pieces, and updates whichever MCP client configs
    it finds on disk:

      - Claude Code        ~/.claude/mcp.json                       [JSON]
      - Claude Desktop     %APPDATA%/Claude/claude_desktop_config.json   [JSON]
      - Codex (Windows)    ~/.codex/config.toml                     [TOML — template only]
      - Gemini CLI         ~/.gemini/settings.json                  [JSON]
      - LM Studio          ~/.lmstudio/mcp.json                     [JSON]

    JSON clients are modified in place after a timestamped backup. The Codex
    TOML config is NOT auto-edited (too fragile to round-trip safely with
    pure PowerShell) — the script prints a copy-pasteable snippet and the
    exact path to append it to.

    If your AI client isn't in that list but speaks MCP, the printed templates
    work for any STDIO-MCP host that uses the same shape.

.PARAMETER InstallDir
    Where voice-mcp.exe lands. Default: %LOCALAPPDATA%\CPC\servers

.PARAMETER PythonExe
    Python executable for `pip install`. Default: auto-detect (python.exe on PATH,
    preferring 3.11+). Pass an explicit path if you have multiple Pythons.

.PARAMETER SkipPython
    Skip pip install — installs only the MCP binary and updates client configs.
    Useful if you only want the AI to *talk*; listening needs Python.

.PARAMETER DryRun
    Print what would happen without modifying anything.

.PARAMETER Verify
    Skip install steps and only report current state (binary present?
    Python deps available? which client configs are wired?).

.EXAMPLE
    .\install.ps1
    # Standard install: binary + Python deps + auto-wire detected client configs.

.EXAMPLE
    .\install.ps1 -InstallDir C:\Tools\voice-mcp -PythonExe C:\Python311\python.exe
    # Custom paths.

.EXAMPLE
    .\install.ps1 -Verify
    # Just tell me what's already in place.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "CPC\servers" } else { Join-Path $HOME ".voice-command\servers" }),
    [string]$PythonExe  = "",
    [switch]$SkipPython,
    [switch]$DryRun,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$script:Repo   = "AIWander/Voice-Command"
$script:Binary = "voice-mcp.exe"

# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

function Write-Step($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Write-Err2($msg)  { Write-Host "    XX  $msg" -ForegroundColor Red }
function Backup-File($path) {
    if (Test-Path $path) {
        $ts  = Get-Date -Format "yyyyMMdd_HHmmss"
        $bak = "$path.bak_$ts"
        Copy-Item $path $bak -Force
        Write-Ok "backup -> $bak"
    }
}

function Detect-Arch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        default { throw "Unsupported architecture: $($env:PROCESSOR_ARCHITECTURE) — Voice-Command ships ARM64 and x64 Windows binaries only." }
    }
}

function Find-Python($explicit) {
    if ($explicit) { return $explicit }
    foreach ($cand in @("python3.11", "python", "py")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) {
            $ver = & $cmd.Source --version 2>&1
            if ($ver -match "Python (3\.(\d+))") {
                if ([int]$Matches[2] -ge 11) { return $cmd.Source }
            }
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# Client config detectors
# ---------------------------------------------------------------------------

$script:Clients = @(
    @{ Name = "Claude Code";     Path = "$env:USERPROFILE\.claude\mcp.json";                     Kind = "json" }
    @{ Name = "Claude Desktop";  Path = "$env:APPDATA\Claude\claude_desktop_config.json";        Kind = "json" }
    @{ Name = "Gemini CLI";      Path = "$env:USERPROFILE\.gemini\settings.json";                Kind = "json" }
    @{ Name = "LM Studio";       Path = "$env:USERPROFILE\.lmstudio\mcp.json";                   Kind = "json" }
    @{ Name = "Codex (Windows)"; Path = "$env:USERPROFILE\.codex\config.toml";                   Kind = "toml" }
)

function Get-DetectedClients {
    $script:Clients | Where-Object { Test-Path $_.Path }
}

# ---------------------------------------------------------------------------
# JSON client editor
# ---------------------------------------------------------------------------

function Add-JsonMcpEntry($path, $exePath) {
    $raw = Get-Content -Raw -Path $path
    if (-not $raw.Trim()) { $raw = "{}" }
    $cfg = $raw | ConvertFrom-Json -AsHashtable
    if (-not $cfg.ContainsKey("mcpServers")) { $cfg["mcpServers"] = @{} }
    if ($cfg["mcpServers"].ContainsKey("voice")) {
        Write-Warn2 "voice entry already present in $path — leaving as-is"
        return $false
    }
    $cfg["mcpServers"]["voice"] = @{ command = $exePath }
    $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $path -Encoding UTF8
    return $true
}

# ---------------------------------------------------------------------------
# TOML template printer (no auto-edit)
# ---------------------------------------------------------------------------

function Show-CodexTomlTemplate($cfgPath, $exePath) {
    Write-Host ""
    Write-Host "    Codex uses TOML. Append this block to:" -ForegroundColor Yellow
    Write-Host "        $cfgPath" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [mcp_servers.voice]" -ForegroundColor White
    Write-Host "    command = `"$($exePath.Replace('\','\\'))`""        -ForegroundColor White
    Write-Host "    cwd     = `"$($InstallDir.Replace('\','\\'))`""     -ForegroundColor White
    Write-Host ""
    Write-Host "    (TOML round-tripping in PowerShell is too fragile to do safely; appending manually is one line.)" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

function Get-LatestRelease {
    Write-Step "Querying GitHub for latest release of $Repo"
    $headers = @{ "User-Agent" = "Voice-Command-install.ps1" }
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    $rel = Invoke-RestMethod -Uri $api -Headers $headers
    Write-Ok "latest release: $($rel.tag_name) ($($rel.assets.Count) assets)"
    return $rel
}

function Download-Binary($release, $arch, $dest) {
    $pattern = "voice-mcp-$arch*.exe"
    $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if (-not $asset) {
        $names = ($release.assets | ForEach-Object { $_.name }) -join ", "
        throw "No asset matching $pattern in release. Available: $names"
    }
    Write-Step "Downloading $($asset.name) -> $dest"
    if ($DryRun) { Write-Warn2 "[dry-run] skipped download"; return }
    Backup-File $dest
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -Headers @{ "User-Agent" = "Voice-Command-install.ps1" }
    Write-Ok "downloaded $((Get-Item $dest).Length) bytes"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Voice-Command installer" -ForegroundColor Magenta
Write-Host "=======================" -ForegroundColor Magenta
Write-Host ""

# Verify mode: just report state.
if ($Verify) {
    Write-Step "Verify mode — reporting state only"
    $binaryPath = Join-Path $InstallDir $Binary
    if (Test-Path $binaryPath) { Write-Ok "binary present: $binaryPath ($((Get-Item $binaryPath).Length) bytes)" } else { Write-Warn2 "binary MISSING at $binaryPath" }
    $py = Find-Python $PythonExe
    if ($py) { Write-Ok "Python found: $py" } else { Write-Warn2 "Python 3.11+ not on PATH (listening server won't run without it)" }
    Write-Step "Client configs detected on this machine:"
    $detected = Get-DetectedClients
    if (-not $detected) { Write-Warn2 "no supported MCP client configs found" }
    foreach ($c in $detected) {
        $hasVoice = (Get-Content -Raw $c.Path) -match "voice"
        $marker = if ($hasVoice) { "voice entry present" } else { "voice entry NOT wired" }
        Write-Ok "$($c.Name) [$($c.Kind)] $($c.Path)  ($marker)"
    }
    exit 0
}

# Step 1 — architecture + binary
$arch = Detect-Arch
Write-Step "Detected architecture: $arch"
if (-not (Test-Path $InstallDir)) {
    Write-Step "Creating install dir: $InstallDir"
    if (-not $DryRun) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
}
$binaryPath = Join-Path $InstallDir $Binary
$release = Get-LatestRelease
Download-Binary $release $arch $binaryPath

# Step 2 — Python deps
if ($SkipPython) {
    Write-Warn2 "skipping Python install (-SkipPython). Listening server will not work; speak-only mode still does."
} else {
    Write-Step "Installing Python listening-server dependencies"
    $py = Find-Python $PythonExe
    if (-not $py) {
        Write-Warn2 "Python 3.11+ not found on PATH. Install Python and re-run, or pass -PythonExe <path>."
        Write-Warn2 "Continuing with config wiring; listening server won't start until Python is installed."
    } else {
        $req = Join-Path $PSScriptRoot "requirements.txt"
        if (-not (Test-Path $req)) {
            Write-Warn2 "requirements.txt not found beside install.ps1 — clone the repo first or pass -SkipPython"
        } else {
            if ($DryRun) { Write-Warn2 "[dry-run] would run: $py -m pip install -r $req" }
            else {
                & $py -m pip install -r $req 2>&1 | Tee-Object -Variable pipOut
                if ($LASTEXITCODE -ne 0) { Write-Err2 "pip install failed — see output above" }
                else { Write-Ok "pip install complete" }
            }
        }
    }
}

# Step 3 — client config wiring
Write-Step "Detecting MCP client configs"
$detected = Get-DetectedClients
if (-not $detected) {
    Write-Warn2 "no client configs found on this machine. Templates printed below — copy the one for your AI."
    foreach ($c in $script:Clients) {
        Write-Host ""
        Write-Host "    --- $($c.Name) ($($c.Path)) ---" -ForegroundColor Yellow
        if ($c.Kind -eq "toml") {
            Show-CodexTomlTemplate $c.Path $binaryPath
        } else {
            $json = @{ mcpServers = @{ voice = @{ command = $binaryPath } } } | ConvertTo-Json -Depth 10
            Write-Host $json -ForegroundColor White
        }
    }
} else {
    foreach ($c in $detected) {
        Write-Step "Wiring $($c.Name): $($c.Path)"
        if ($DryRun) {
            Write-Warn2 "[dry-run] would update $($c.Path)"
            continue
        }
        Backup-File $c.Path
        if ($c.Kind -eq "json") {
            $added = Add-JsonMcpEntry -path $c.Path -exePath $binaryPath
            if ($added) { Write-Ok "added voice entry to $($c.Name)" }
        } else {
            # TOML — print template, don't auto-edit.
            Show-CodexTomlTemplate $c.Path $binaryPath
        }
    }
}

# Step 4 — summary + verify-by-saying-hi
Write-Host ""
Write-Step "Install summary"
Write-Ok "binary: $binaryPath"
if ($py) { Write-Ok "Python: $py" }
$jsonClients = $detected | Where-Object { $_.Kind -eq "json" }
$tomlClients = $detected | Where-Object { $_.Kind -eq "toml" }
if ($jsonClients) { Write-Ok "auto-wired: $(($jsonClients | ForEach-Object { $_.Name }) -join ', ')" }
if ($tomlClients) { Write-Warn2 "manual add still needed: $(($tomlClients | ForEach-Object { $_.Name }) -join ', ')  (template printed above)" }

Write-Host ""
Write-Host "==> Ready to talk" -ForegroundColor Magenta
Write-Host "    1. Start the listening server:    START_VOICE_SERVER.bat (or pythonw voice_server.py -WindowStyle Hidden)"
Write-Host "    2. If your client needs reloading, do that now. Most don't — try it without first."
Write-Host "    3. Ask your AI:  'say hi out loud and then listen for me'"
Write-Host "    If you hear a voice say hi and then hear the listen-beep, you're wired up. Talk back to confirm the round-trip."
Write-Host ""
Write-Host "    If you hear the beep but transcription stays silent: Windows Settings -> Privacy & security -> Microphone" -ForegroundColor DarkGray
Write-Host "    -> confirm 'Let desktop apps access your microphone' is ON. Most installs have it on by default." -ForegroundColor DarkGray
Write-Host ""
