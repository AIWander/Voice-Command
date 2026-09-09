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
  #define AppVersion "3.1.0"
#endif
#ifndef PayloadMaxRelLen
  ; Longest path INSIDE the payload, relative to {app}, in characters.
  ; Measured 2026-09-09 = 159, in the bundled ONNX test-data tree:
  ;   python\Lib\site-packages\onnx\backend\test\data\node\
  ;   test_attention_4d_with_past_and_present_qk_matmul_bias_3d_mask_causal_expanded\
  ;   test_data_set_0\output_0.pb
  ; The ONNX tree dominates; the deepest plugin path is only 108.
  ; build-full-installer.cmd re-measures the real runtime root and passes
  ; /DPayloadMaxRelLen, so this default cannot silently rot when the payload grows.
  #define PayloadMaxRelLen 159
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
WelcomeLabel2=Installs the complete bundled CPC Voice runtime for {#Arch}: private Python, a local speech-to-text model, Voice App, current Rust MCP wrapper, plugin metadata, three voice skills, and inert opt-in hook templates that are never wired for you. Speech output through edge-tts requires network access. The installer copies per-AI activation instructions to the clipboard and shows both a popup and terminal handoff. It does not edit AI configs, auto-trust a plugin, or open the microphone.

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#RuntimeRoot}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeRoot}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeRoot}\app\voice_app.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#RuntimeRoot}\app\voice_interrupt.py"; DestDir: "{app}\app"; Flags: ignoreversion
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

[InstallDelete]
Type: files; Name: "{app}\clipboard-status.txt"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\marketplace"
Type: filesandordirs; Name: "{app}\installer"
Type: files; Name: "{app}\APPLY_TO_YOUR_AI.txt"
Type: files; Name: "{app}\install-result.json"
Type: files; Name: "{app}\clipboard-status.txt"

[Code]
// ---------------------------------------------------------------------------
// Destination-length guard (release blocker, fixed 2026-09-09).
//
// Windows caps a usable path at 259 characters. This installer copies a bundled
// CPython tree whose deepest entry sits PayloadMaxRelLen characters below the
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
    'CPC Voice bundles a private Python runtime whose deepest file sits ' +
    '{#PayloadMaxRelLen} characters below the installation folder, and Windows ' +
    'cannot create paths longer than 259 characters. Installing here would fail ' +
    'partway through and roll back.' #13#10 #13#10 +
    'Please choose a shorter folder, for example:' #13#10 +
    ExpandConstant('{userpf}') + '\CPC\VoiceApp';
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
