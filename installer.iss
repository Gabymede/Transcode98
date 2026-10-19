[Setup]
AppName=Transcode 98
AppVersion=1.0
DefaultDirName={autopf}\Transcode98
DefaultGroupName=Transcode 98
OutputDir=installer_out
OutputBaseFilename=Transcode98_Setup
Compression=lzma2/max
SolidCompression=yes
DisableProgramGroupPage=yes
WizardStyle=modern

[Files]
Source: "dist\Transcode98\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Transcode 98"; Filename: "{app}\Transcode98.exe"
Name: "{autodesktop}\Transcode 98"; Filename: "{app}\Transcode98.exe"; \
  Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; \
  GroupDescription: "Дополнительно:"

[Run]
Filename: "{app}\Transcode98.exe"; Description: "Запустить Transcode 98"; \
  Flags: nowait postinstall skipifsilent