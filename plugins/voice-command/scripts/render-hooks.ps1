[CmdletBinding()]
param(
    [string] $PluginRoot,
    [string] $OutputDir
)

$ErrorActionPreference = 'Stop'
if (-not $PluginRoot) {
    $PluginRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $PluginRoot 'rendered-hooks'
}

$resolvedRoot = [System.IO.Path]::GetFullPath($PluginRoot)
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDir)
$rootPrefix = $resolvedRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not (
    $resolvedOutput.Equals($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $resolvedOutput.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
)) {
    throw 'OutputDir must stay inside PluginRoot.'
}

$sourceDir = Join-Path $resolvedRoot 'hooks\opt-in'
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
$portableRoot = $resolvedRoot.Replace('\', '/')
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

Get-ChildItem -LiteralPath $sourceDir -Filter '*.fragment.json' -File | ForEach-Object {
    $content = Get-Content -Raw -LiteralPath $_.FullName
    $rendered = $content.Replace('__VOICE_COMMAND_PLUGIN_ROOT__', $portableRoot)
    $null = $rendered | ConvertFrom-Json
    $name = $_.Name.Replace('.fragment', '')
    $destination = Join-Path $resolvedOutput $name
    [System.IO.File]::WriteAllText($destination, $rendered, $utf8NoBom)
    [pscustomobject]@{
        Source = $_.FullName
        Destination = $destination
        Sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    }
}
