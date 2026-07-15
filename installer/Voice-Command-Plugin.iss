; Voice-Command optional plugin installer (Inno Setup 6)
; Installs the Rust MCP executable, Codex and Claude-compatible plugin files,
; skills, local marketplace metadata, and a clipboard-based activation guide.
; It does not edit or trust any AI client configuration and never starts the mic.

#ifndef Arch
  #define Arch "arm64"
#endif
#ifndef VoiceExe
  #error VoiceExe must point to a built voice-mcp executable.
#endif
#ifndef AppVersion
  #define AppVersion "0.3.1"
#endif
#define RepoRoot SourcePath + ".."
#define PluginRoot RepoRoot + "\plugins\voice-command"
#if Arch == "arm64"
  #define ArchSpec "arm64"
#else
  #define ArchSpec "x64compatible"
#endif

[Setup]
AppId={{52AA0A17-4A61-4F8D-8FB6-0EA4A4C09DBD}
AppName=Voice-Command Plugin
AppVersion={#AppVersion}
AppPublisher=AIWander
AppPublisherURL=https://github.com/AIWander/Voice-Command
DefaultDirName={localappdata}\AIWander\Voice-Command
DefaultGroupName=AIWander Voice-Command
OutputDir={#RepoRoot}\dist
OutputBaseFilename=Voice-Command-Plugin-Setup-{#Arch}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed={#ArchSpec}
ArchitecturesInstallIn64BitMode={#ArchSpec}
DisableProgramGroupPage=yes
WizardStyle=modern
ChangesEnvironment=no
UninstallDisplayName=Voice-Command Plugin v{#AppVersion}
UninstallDisplayIcon={app}\bin\voice-mcp.exe
LicenseFile={#RepoRoot}\LICENSE

[Messages]
WelcomeLabel2=Installs the optional Voice-Command Rust MCP wrapper, plugin metadata, and two voice skills. It stages a local marketplace, copies per-AI activation instructions to the clipboard, and shows both a popup and terminal handoff. It does not edit AI configs, auto-trust a plugin, start the listener, or open the microphone.

[Files]
Source: "{#VoiceExe}"; DestDir: "{app}\bin"; DestName: "voice-mcp.exe"; Flags: ignoreversion
Source: "{#PluginRoot}\*"; DestDir: "{app}\marketplace\plugins\voice-command"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\.agents\plugins\marketplace.json"; DestDir: "{app}\marketplace\.agents\plugins"; Flags: ignoreversion
Source: "{#RepoRoot}\.claude-plugin\marketplace.json"; DestDir: "{app}\marketplace\.claude-plugin"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\APPLY_TO_YOUR_AI.txt"; DestDir: "{app}\installer"; DestName: "APPLY_TO_YOUR_AI.template.txt"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Finalize-Install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Notify-Install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "{#RepoRoot}\installer\Show-Install-Instructions.cmd"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\Voice-Command activation instructions"; Filename: "{app}\APPLY_TO_YOUR_AI.txt"
Name: "{group}\Uninstall Voice-Command Plugin"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Finalize-Install.ps1"" -AppDir ""{app}"""; StatusMsg: "Rendering the local plugin and activation guide..."; Flags: runhidden waituntilterminated
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -File ""{app}\installer\Notify-Install.ps1"" -AppDir ""{app}"""; StatusMsg: "Copying per-AI instructions to the clipboard..."; Flags: runhidden waituntilterminated skipifsilent
Filename: "{cmd}"; Parameters: "/K ""{app}\installer\Show-Install-Instructions.cmd"""; Description: "Show the activation instructions in a terminal"; Flags: postinstall nowait skipifsilent

[InstallDelete]
Type: files; Name: "{app}\clipboard-status.txt"

[UninstallDelete]
Type: files; Name: "{app}\APPLY_TO_YOUR_AI.txt"
Type: files; Name: "{app}\install-result.json"
Type: files; Name: "{app}\clipboard-status.txt"
Type: filesandordirs; Name: "{app}\marketplace"
Type: filesandordirs; Name: "{app}\installer"
Type: filesandordirs; Name: "{app}\bin"
