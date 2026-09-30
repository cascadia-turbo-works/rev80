; rev80.iss  —  Inno Setup script
;
; Rev80 — Desktop GUI for PicoScope vibration analysis
; Copyright (c) 2026 Rev Engineering. Author: Henry Gotjen.
; Released under the MIT License.
;
; Requirements:
;   Inno Setup 6.x  https://jrsoftware.org/isinfo.php
;
; Usage (from the repository root, after the PyInstaller step, which writes
; installer\version.iss and dist\rev80\):
;   iscc installer\rev80.iss
;
; Output:
;   installer\Output\Rev80Setup-x.y.z.exe

#define AppName      "Rev80"
#include "version.iss"
#define AppPublisher "Rev Engineering"
#define AppCopyright "Copyright (c) 2026 Rev Engineering. Author: Henry Gotjen."
#define AppExeName   "rev80.exe"
#define AppIcon      "..\assets\icons\rev80.ico"
; Directory produced by PyInstaller COLLECT step
#define BuildDir     "..\dist\rev80"

[Setup]
; Do not change AppId. Setup uses it to find an earlier install for upgrade
; and uninstall.
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppCopyright}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=Rev80Setup-{#AppVersion}
SetupIconFile={#AppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Require Windows 10 (build 1809+) — needed for modern DearPyGui renderer
MinVersion=10.0.17763
WizardStyle=modern
; No admin rights necessary. A per-user install goes to
; %LOCALAPPDATA%\Programs. The dialog lets the user install for all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller one-dir bundle
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";   Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\rev80.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\rev80.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Empty on purpose. The uninstaller does not delete the user data
; (Documents\Rev80\ and %APPDATA%\rev80\).

[Code]
// ── PicoSDK prerequisite check ──────────────────────────────────────────────
// A release (nodlls) installer bundles no PicoSDK DLL. A local build bundles
// ps4000a.dll and picoipp.dll. The USB kernel driver always comes from
// PicoSDK. Warn, do not block: a site can install PicoSDK by group policy,
// or later.

function IsPicoSdkInstalled(): Boolean;
var
  RegPath: String;
begin
  // PicoSDK 11.x writes no registry key. Thus also check the default DLL
  // location.
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\Pico Technology\SDK', 'InstallPath', RegPath)
         or RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Pico Technology\SDK', 'InstallPath', RegPath)
         or FileExists(ExpandConstant('{pf}\Pico Technology\SDK\lib\ps4000a.dll'))
         or FileExists(ExpandConstant('{pf32}\Pico Technology\SDK\lib\ps4000a.dll'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsPicoSdkInstalled() then
  begin
    if MsgBox(
      'PicoSDK does not appear to be installed on this machine.' + #13#10 +
      'Rev80 will launch but will not be able to connect to a PicoScope ' +
      'until PicoSDK is installed.' + #13#10#13#10 +
      'Download PicoSDK from: https://www.picotech.com/downloads' + #13#10#13#10 +
      'Continue with Rev80 installation?',
      mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
