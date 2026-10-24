; Instalador do SofaHub (Inno Setup 6)
; Gerado pelo build.bat ou pelo GitHub Actions. Instala só para o usuário atual: não pede administrador.
; Os dados (PIN, celulares, logins do navegador) ficam em %LOCALAPPDATA%\SofaHub e sobrevivem a
; atualizações e à desinstalação.

#ifndef AppVersion
  #define AppVersion "0.7.2"
#endif

[Setup]
AppId={{6B1F2C8E-5A4D-4C1B-9E7F-50FA0B0C1D21}
AppName=SofaHub
AppVersion={#AppVersion}
AppVerName=SofaHub {#AppVersion}
AppPublisher=SofaHub
DefaultDirName={autopf}\SofaHub
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=SofaHub-Setup-{#AppVersion}
SetupIconFile=..\web\icon.ico
UninstallDisplayIcon={app}\SofaHub.exe
UninstallDisplayName=SofaHub
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=force
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "inicio"; Description: "Iniciar o SofaHub junto com o Windows (recomendado)"
Name: "desktop"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked

[InstallDelete]
; versões antigas podem deixar arquivos que não existem mais
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\SofaHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SofaHub"; Filename: "{app}\SofaHub.exe"
Name: "{autodesktop}\SofaHub"; Filename: "{app}\SofaHub.exe"; Tasks: desktop

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SofaHub"; \
  ValueData: """{app}\SofaHub.exe"""; Tasks: inicio; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SofaHub.exe"; Parameters: "--configurar"; Description: "Abrir o SofaHub agora"; \
  Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im SofaHub.exe /f"; Flags: runhidden; RunOnceId: "FecharSofaHub"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  { fecha o SofaHub antes de atualizar }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/im SofaHub.exe /f', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
