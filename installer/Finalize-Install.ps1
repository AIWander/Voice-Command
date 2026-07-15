[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = 'Stop'

$appRoot = [System.IO.Path]::GetFullPath($AppDir)
$marketplaceRoot = Join-Path $appRoot 'marketplace'
$pluginRoot = Join-Path $marketplaceRoot 'plugins\voice-command'
$voiceExe = @(
    (Join-Path $appRoot 'voice.exe'),
    (Join-Path $appRoot 'bin\voice-mcp.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$mcpPath = Join-Path $pluginRoot '.mcp.json'
$templatePath = Join-Path $appRoot 'installer\APPLY_TO_YOUR_AI.template.txt'
$instructionsPath = Join-Path $appRoot 'APPLY_TO_YOUR_AI.txt'

if (-not $voiceExe) {
    throw 'No installed Voice-Command Rust executable was found.'
}

foreach ($required in @($mcpPath, $templatePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required installed file is missing: $required"
    }
}

$mcp = Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json
if (-not $mcp.mcpServers.voice) {
    throw 'Installed .mcp.json does not contain mcpServers.voice.'
}
$mcp.mcpServers.voice.command = $voiceExe
$mcpJson = $mcp | ConvertTo-Json -Depth 20
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($mcpPath, $mcpJson + [Environment]::NewLine, $utf8NoBom)

$instructions = [System.IO.File]::ReadAllText($templatePath)
$instructions = $instructions.Replace('__MARKETPLACE_ROOT__', $marketplaceRoot)
$instructions = $instructions.Replace('__PLUGIN_ROOT__', $pluginRoot)
$instructions = $instructions.Replace('__VOICE_EXE__', $voiceExe)
[System.IO.File]::WriteAllText($instructionsPath, $instructions, $utf8NoBom)

$result = [ordered]@{
    schema = 'voice-command-plugin-install-v1'
    marketplace_root = $marketplaceRoot
    plugin_root = $pluginRoot
    voice_exe = $voiceExe
    instructions = $instructionsPath
    full_runtime_bundled = [bool](
        (Test-Path -LiteralPath (Join-Path $appRoot 'python') -PathType Container) -and
        (Test-Path -LiteralPath (Join-Path $appRoot 'models') -PathType Container) -and
        (Test-Path -LiteralPath (Join-Path $appRoot 'app\voice_app.py') -PathType Leaf)
    )
    client_configs_changed = $false
    microphone_started = $false
}
$resultJson = $result | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $appRoot 'install-result.json'), $resultJson + [Environment]::NewLine, $utf8NoBom)
