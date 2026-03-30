; vibechecker.iss  —  Inno Setup script
;
; Creates a Windows installer for Vibechecker.
;
; Requirements:
;   Inno Setup 6.x  https://jrsoftware.org/isinfo.php
;
; Usage (from project root after PyInstaller build):
;   iscc installer\vibechecker.iss
;
; Output:
;   installer\Output\VibecheckerSetup-x.y.z.exe

#define AppName      "Vibechecker"
#define AppVersion   "0.1.0"
#define AppPublisher "Henry Gotjen"
#define AppExeName   "vibechecker.exe"
#define AppIcon      "..\assets\vibechecker.ico"
; Directory produced by PyInstaller COLLECT step
#define BuildDir     "..\dist\vibechecker"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=VibecheckerSetup-{#AppVersion}
SetupIconFile={#AppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
; Require Windows 10 (build 1809+) — needed for modern DearPyGui renderer
MinVersion=10.0.17763
WizardStyle=modern
; Do NOT require admin rights — install to %LOCALAPPDATA% if not admin
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
Name: "{group}\{#AppName}";   Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\vibechecker.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\vibechecker.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove user data directory only if user explicitly opts in (do not auto-delete)

[Code]
// ── PicoSDK prerequisite check ──────────────────────────────────────────────
// Vibechecker bundles the user-mode DLLs (ps4000a.dll, picoipp.dll) but the
// USB kernel driver must be installed separately via PicoSDK.
// We warn the user rather than hard-blocking, since some sites pre-install
// PicoSDK via group policy or the device may be connected later.

function IsPicoSdkInstalled(): Boolean;
var
  RegPath: String;
begin
  // PicoSDK 11.x does not write a registry key — fall back to checking the
  // well-known default DLL location.
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
      'Vibechecker will launch but will not be able to connect to a PicoScope ' +
      'until PicoSDK is installed.' + #13#10#13#10 +
      'Download PicoSDK from: https://www.picotech.com/downloads' + #13#10#13#10 +
      'Continue with Vibechecker installation?',
      mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
