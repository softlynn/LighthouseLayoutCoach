; Inno Setup installer for LighthouseLayoutCoach

#define MyAppName "LighthouseLayoutCoach"
#define MyAppExeName "LighthouseLayoutCoach.exe"
#define MyAppPublisher "Softlynn"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif

#define VcRedistPath "..\\packaging\\redist\\vc_redist.x64.exe"
#define OverlayHelperPath "..\\dist\\overlay\\LighthouseLayoutCoachOverlay.exe"

#ifexist "{#VcRedistPath}"
#define BundleVcRedist
#endif

#ifexist "{#OverlayHelperPath}"
#define BundleOverlayHelper
#endif

[Setup]
AppId={{7E4C4B30-0E73-4C9A-B7B0-1E1C1E7D58D1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Softlynn/LighthouseLayoutCoach
AppSupportURL=https://github.com/Softlynn/LighthouseLayoutCoach/issues
AppUpdatesURL=https://github.com/Softlynn/LighthouseLayoutCoach/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=LighthouseLayoutCoach_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\installer\installer_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Dirs]
Name: "{localappdata}\{#MyAppName}\tmp"

[Files]
; Install the onedir build to avoid onefile _MEI extraction issues.
Source: "..\dist\LighthouseLayoutCoach\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Onedir overlay helper (avoids onefile temp extraction/cleanup dialogs when starting/stopping VR mode)
#ifdef BundleOverlayHelper
Source: "{#OverlayHelperPath}"; DestDir: "{app}\overlay"; Flags: ignoreversion
#endif
; Optional dependency installer (bundled by scripts/build_windows.ps1 when available)
#ifdef BundleVcRedist
Source: "{#VcRedistPath}"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
#endif

[Icons]
Name: "{group}\Lighthouse Layout Coach (Launcher)"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Lighthouse Layout Coach (Desktop)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--desktop"
Name: "{group}\Lighthouse Layout Coach (VR Overlay)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--vr"
Name: "{commondesktop}\Lighthouse Layout Coach"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Lighthouse Layout Coach"; Flags: nowait postinstall skipifsilent
#ifdef BundleVcRedist
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Runtime…"; Flags: waituntilterminated runhidden; Check: VcRedistNeedsInstall
#endif

[Code]
function VcRegKey: string;
begin
  Result := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
end;

function VcRedistInstalled: Boolean;
var
  installed: Cardinal;
begin
  Result := False;
  installed := 0;
  if RegQueryDWordValue(HKLM, VcRegKey, 'Installed', installed) then begin
    Result := (installed = 1);
    exit;
  end;
  if RegQueryDWordValue(HKLM32, VcRegKey, 'Installed', installed) then begin
    Result := (installed = 1);
    exit;
  end;
end;

function VcRedistNeedsInstall: Boolean;
begin
  Result := (not VcRedistInstalled());
end;
