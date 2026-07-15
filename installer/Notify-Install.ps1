[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = 'Stop'
$instructionsPath = Join-Path ([System.IO.Path]::GetFullPath($AppDir)) 'APPLY_TO_YOUR_AI.txt'
$instructions = [System.IO.File]::ReadAllText($instructionsPath)

try {
    Set-Clipboard -Value $instructions -ErrorAction Stop
}
catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.Clipboard]::SetText($instructions)
}

Add-Type -AssemblyName System.Windows.Forms
$message = 'Voice-Command is installed but not enabled. The per-AI activation instructions are now on your clipboard. Paste them into Codex, Claude, Grok, or another AI, or follow the terminal window. No AI config was changed and the microphone was not started.'
[void][System.Windows.Forms.MessageBox]::Show(
    $message,
    'Voice-Command installation complete',
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
)
