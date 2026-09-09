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
  #define AppVersion "0.4.0"
#endif
#define RepoRoot SourcePath + ".."
#define PluginRoot RepoRoot + "\plugins\voice-command"
#if Arch == "arm64"
  #define ArchSpec "arm64"
#else
  #define ArchSpec "x64compatible"
#endif

#ifndef PayloadMaxRelLen
  ; Longest path INSIDE the payload, relative to {app}, in characters.
  ; Measured 2026-09-09 = 108: the plugin tree is copied under
  ; marketplace\plugins\voice-command (34 chars) and its own deepest entry is
  ; hooks\opt-in\adapters\claude-grok\__pycache__\hook_adapter.cpython-312.pyc (74).
  ; Smaller than the full installer's 159 because no Python runtime ships here.
  #define PayloadMaxRelLen 108
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
WelcomeLabel2=Installs the optional Voice-Command Rust MCP wrapper, plugin metadata, three voice skills, and inert opt-in hook templates that are never wired for you. It stages a local marketplace, copies per-AI activation instructions to the clipboard, and shows both a popup and terminal handoff. It does not edit AI configs, auto-trust a plugin, start the listener, or open the microphone.

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

[Code]
// ---------------------------------------------------------------------------
// Destination-length guard. Same defect class as the full installer.
//
// Windows caps a usable path at 259 characters. This payload has no Python runtime,
// but its deepest entry still sits PayloadMaxRelLen characters below the
// application directory, so any destination longer than
// (259 - 1 - PayloadMaxRelLen) makes file creation fail partway through.
//
// The observed failure was NOT a clean error: at a 254-character destination the
// ONNX payload could not be created, Setup exited 5, and the whole install
// rolled back after minutes of copying. This rejects BEFORE any file is written.
//
// Two entry points on purpose:
//   NextButtonClick  - interactive runs, so the user is told at the folder page
//                      while the folder is still easy to change.
//   PrepareToInstall - the real gate. Also covers /SILENT, /VERYSILENT and
//                      /DIR=, where no wizard page is shown; a non-empty result
//                      aborts before the first file copy.
//
// NOTE for future editors: do NOT use Pascal brace comments in this section.
// A brace comment containing a constant such as the app-dir constant is closed
// early by that constant's own closing brace, and the remainder parses as code.
// That mistake produced "Column 29: 'BEGIN' expected" on first compile here.
// ---------------------------------------------------------------------------

function MaxAppDirLen: Integer;
begin
  // 259 usable characters, minus the separator before the relative path.
  Result := 259 - 1 - {#PayloadMaxRelLen};
end;

function TooLongMessage(const Dir: String): String;
begin
  Result :=
    'The installation folder is too long for Windows.' #13#10 #13#10 +
    'Chosen folder (' + IntToStr(Length(Dir)) + ' characters):' #13#10 +
    Dir + #13#10 #13#10 +
    'Maximum for this installer: ' + IntToStr(MaxAppDirLen) + ' characters.' #13#10 #13#10 +
    'Files in this package sit up to {#PayloadMaxRelLen} characters below the ' +
    'installation folder, and Windows cannot create paths longer than 259 ' +
    'characters. Installing here would fail partway through.' #13#10 #13#10 +
    'Please choose a shorter folder.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if Length(WizardDirValue) > MaxAppDirLen then
    begin
      MsgBox(TooLongMessage(WizardDirValue), mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir: String;
begin
  Result := '';
  NeedsRestart := False;
  Dir := ExpandConstant('{app}');
  if Length(Dir) > MaxAppDirLen then
    Result := TooLongMessage(Dir);
end;
