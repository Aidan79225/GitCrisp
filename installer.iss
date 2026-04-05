#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{91c943cb-d556-4427-a45b-08512cf9a37b}
AppName=GitStack
AppVersion={#AppVersion}
AppPublisher=Aidan Wang
DefaultDirName={autopf}\GitStack
DefaultGroupName=GitStack
UninstallDisplayIcon={app}\GitStack.exe
OutputBaseFilename=GitStack-windows-setup
OutputDir=.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\GitStack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GitStack"; Filename: "{app}\GitStack.exe"
Name: "{group}\Uninstall GitStack"; Filename: "{uninstallexe}"
Name: "{userdesktop}\GitStack"; Filename: "{app}\GitStack.exe"; Tasks: desktopicon
