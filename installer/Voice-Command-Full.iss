; Voice-Command full bundled installer (Inno Setup 6)
; Bundles the private Python runtime, speech model, Voice App, current Rust MCP
; wrapper, portable plugin, skills, marketplaces, and per-AI activation guide.
; It stages every component but never edits or trusts an AI client configuration.

#ifndef Arch
  #define Arch "arm64"
#endif
#ifndef VoiceExe
  #error VoiceExe must point to a built voice-mcp executable.
#endif
#ifndef RuntimeRoot
  #error RuntimeRoot must contain python, models, app, and Start-CPC-Voice.bat.
#endif
#ifndef AppVersion
  #define AppVersion "3.0.0"
#endif
#define RepoRoot SourcePath + ".."
#define PluginRoot RepoRoot + "\plugins\voice-command"
#if Arch == "arm64"
  #define ArchSpec "arm64"
#else
  #define ArchSpec "x64compatible"
#endif

[Setup]
AppId={{C9E7A3F2-5B1D-4E6A-9C2F-7A8B0D1E2F34}
AppName=CPC Voice
AppVersion={#AppVersion}
AppPublisher=AIWander
AppPublisherURL=https://github.com/AIWander/Voice-Command
DefaultDirName={userpf}\CPC\VoiceApp
DefaultGroupName=CPC Voice
OutputDir={#RepoRoot}\dist
OutputBaseFilename=CPC-Voice-Setup-{#Arch}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed={#ArchSpec}
ArchitecturesInstallIn64BitMode={#ArchSpec}
DisableProgramGroupPage=yes
WizardStyle=modern
ChangesEnvironment=no
UninstallDisplayName=CPC Voice v{#AppVersion}
UninstallDisplayIcon={app}\voice.exe
LicenseFile={#RepoRoot}\LICENSE

[Messages]
WelcomeLabel2=Installs the complete bundled CPC Voice runtime for {#Arch}: private Python, a local speech-to-text model, Voice App, current Rust MCP wrapper, plugin metadata, and two voice skills. Speech output through edge-tts requires network access. The installer copies per-AI activation instructions to the clipboard and shows both a popup and terminal handoff. It does not edit AI configs, auto-trust a plugin, or open the microphone.

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#RuntimeRoot}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeRoot}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeRoot}\app\voice_app.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#RuntimeRoot}\app\voice.config.toml"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#RuntimeRoot}\Start-CPC-Voice.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#VoiceExe}"; DestDir: "{app}"; DestName: "voice.exe"; Flags: ignoreversion
Source: "{#PluginRoot}\*"; DestDir: "{app}\marketplace\plugins\voice-command"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\.agents\plugins\marketplace.json"; DestDir: "{app}\marketplace\.agents\plugins"; Flags: ignoreversion
Source: "{#RepoRoot}\.claude-plugin\marketplace.json"; DestDir: "{app}\marketplace\.claude-plugin"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\APPLY_TO_YOUR_AI.txt"; DestDir: "{app}\installer"; DestName: "APPLY_TO_YOUR_AI.template.txt"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Finalize-Install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Notify-Install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Show-Install-Instructions.cmd"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\CPC Voice"; Filename: "{app}\Start-CPC-Voice.bat"; IconFilename: "{app}\voice.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\CPC Voice"; Filename: "{app}\Start-CPC-Voice.bat"; IconFilename: "{app}\voice.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Voice-Command activation instructions"; Filename: "{app}\APPLY_TO_YOUR_AI.txt"
Name: "{group}\Uninstall CPC Voice"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Finalize-Install.ps1"" -AppDir ""{app}"""; StatusMsg: "Rendering the local plugin and activation guide..."; Flags: runhidden waituntilterminated
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -File ""{app}\installer\Notify-Install.ps1"" -AppDir ""{app}"""; StatusMsg: "Copying per-AI instructions to the clipboard..."; Flags: runhidden waituntilterminated skipifsilent
Filename: "{cmd}"; Parameters: "/K ""{app}\installer\Show-Install-Instructions.cmd"""; Description: "Show the activation instructions in a terminal"; Flags: postinstall nowait skipifsilent
Filename: "{app}\Start-CPC-Voice.bat"; Description: "Start CPC Voice now (does not open the microphone)"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\marketplace"
Type: filesandordirs; Name: "{app}\installer"
Type: files; Name: "{app}\APPLY_TO_YOUR_AI.txt"
Type: files; Name: "{app}\install-result.json"
