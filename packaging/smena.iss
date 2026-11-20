; Установщик SMENA для Windows (Inno Setup 6). Собирается из dist\SMENA (PyInstaller):
;   iscc /DAppVersion=0.1.2 /DSrcDir=build\dist\SMENA /DOutDir=build\out packaging\smena.iss
; Ставится для текущего пользователя (без прав администратора) в %LOCALAPPDATA%\Programs\SMENA.
; Визуал — на дискретной видеокарте: ключ UserGpuPreferences для SMENA.exe (то же, что «Параметры → Дисплей → Графика»).
; Настройки и пресеты (%APPDATA%\SMENA) при удалении не трогаются.

#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif
#ifndef SrcDir
  #define SrcDir "..\build\dist\SMENA"
#endif
#ifndef OutDir
  #define OutDir "..\build\out"
#endif

[Setup]
AppId={{6C1E5B0A-3F7D-4E7B-9A51-5E3A0C1D2B71}
AppName=SMENA
AppVersion={#AppVersion}
AppVerName=SMENA {#AppVersion}
AppPublisher=SMENA
AppPublisherURL=https://github.com/
DefaultDirName={localappdata}\Programs\SMENA
DefaultGroupName=SMENA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=SMENA_Setup-{#AppVersion}
SetupIconFile=icons\smena.ico
UninstallDisplayIcon={app}\SMENA.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SMENA"; Filename: "{app}\SMENA.exe"
Name: "{group}\{cm:UninstallProgram,SMENA}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SMENA"; Filename: "{app}\SMENA.exe"; Tasks: desktopicon

[Registry]
; 2 = «высокая производительность» (дискретная видеокарта)
Root: HKCU; Subkey: "Software\Microsoft\DirectX\UserGpuPreferences"; ValueType: string; ValueName: "{app}\SMENA.exe"; ValueData: "GpuPreference=2;"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SMENA.exe"; Description: "{cm:LaunchProgram,SMENA}"; Flags: nowait postinstall skipifsilent
