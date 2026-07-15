[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,

    [switch]$ForceClipboardFailure,

    [switch]$NoUi
)

$ErrorActionPreference = 'Stop'
$appRoot = [System.IO.Path]::GetFullPath($AppDir)
$instructionsPath = Join-Path $appRoot 'APPLY_TO_YOUR_AI.txt'
$statusPath = Join-Path $appRoot 'clipboard-status.txt'
$instructions = $null

try {
    $instructions = [System.IO.File]::ReadAllText($instructionsPath)
    if ([string]::IsNullOrWhiteSpace($instructions)) {
        $instructions = $null
    }
}
catch {
    $instructions = $null
}

$clipboardCopied = $false
if ($null -ne $instructions) {
    try {
        if ($ForceClipboardFailure) {
            throw 'Forced Set-Clipboard failure for a headless behavior test.'
        }
        Set-Clipboard -Value $instructions -ErrorAction Stop
        $clipboardCopied = $true
    }
    catch {
        try {
            if ($ForceClipboardFailure) {
                throw 'Forced Windows Forms clipboard failure for a headless behavior test.'
            }
            Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
            [System.Windows.Forms.Clipboard]::SetText($instructions)
            $clipboardCopied = $true
        }
        catch {
            $clipboardCopied = $false
        }
    }
}

if ($clipboardCopied) {
    $clipboardStatus = 'copied'
    $message = 'Voice-Command is installed but not enabled. The per-AI activation instructions were copied to your clipboard. Paste them into Codex, Claude, Grok, or another AI, or follow the terminal window. No AI config was changed and the microphone was not started.'
}
elseif ($null -ne $instructions) {
    $clipboardStatus = 'unavailable'
    $message = "Voice-Command is installed but not enabled. Clipboard copy was unavailable. Open the activation guide at:`n`n$instructionsPath`n`nNo AI config was changed and the microphone was not started."
}
else {
    $clipboardStatus = 'instructions-missing'
    $message = "Voice-Command installed, but its activation guide could not be loaded. Re-run the installer or open the expected guide at:`n`n$instructionsPath`n`nNo AI config was changed and the microphone was not started."
}

try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($statusPath, $clipboardStatus + [Environment]::NewLine, $utf8NoBom)
}
catch {
    $message += "`n`nThe clipboard status file could not be written."
}

Write-Output $message

if (-not $NoUi) {
    $notificationShown = $false
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [void][System.Windows.Forms.MessageBox]::Show(
            $message,
            'Voice-Command installation complete',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
        $notificationShown = $true
    }
    catch {
        $notificationShown = $false
    }

    if (-not $notificationShown) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            [void]$shell.Popup($message, 0, 'Voice-Command installation complete', 64)
        }
        catch {
            Write-Warning "Could not open the installation-complete popup. $message"
        }
    }
}
