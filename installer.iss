#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{91c943cb-d556-4427-a45b-08512cf9a37b}
AppName=GitCrisp
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Aidan Wang
DefaultDirName={autopf}\GitCrisp
DefaultGroupName=GitCrisp
UninstallDisplayIcon={app}\GitCrisp.exe
; The wizard's own icon. Without it the installer ships with Inno's default,
; which is the first thing a user sees of the app.
SetupIconFile=arts\gitcrisp.ico
OutputBaseFilename=GitCrisp-windows-setup
OutputDir=.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\GitCrisp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GitCrisp"; Filename: "{app}\GitCrisp.exe"
Name: "{group}\Uninstall GitCrisp"; Filename: "{uninstallexe}"
Name: "{userdesktop}\GitCrisp"; Filename: "{app}\GitCrisp.exe"; Tasks: desktopicon
