@echo off
REM Gera o SofaHub.exe (dist\SofaHub) e, se o Inno Setup estiver instalado, o instalador
REM (instalador\Output\SofaHub-Setup-x.y.z.exe).
cd /d "%~dp0"

echo [1/3] Instalando dependencias...
python -m pip install -q -r requirements.txt pyinstaller || goto :erro

echo [2/3] Gerando o SofaHub.exe...
python -m PyInstaller --noconfirm --clean --windowed --name SofaHub --icon web\icon.ico ^
  --add-data "web;web" --add-data "extensao;extensao" --add-data "presets.json;." ^
  --hidden-import segno --hidden-import icones --hidden-import navegadores sofahub.py || goto :erro

for /f "tokens=2 delims==" %%v in ('findstr /b "VERSAO" servidor.py') do set VERSAO=%%~v
set VERSAO=%VERSAO: =%
set VERSAO=%VERSAO:"=%

echo [3/3] Gerando o instalador (versao %VERSAO%)...
set ISCC=
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if exist %%p set ISCC=%%p
)
if not defined ISCC (
  echo.
  echo Inno Setup nao encontrado: so o .exe foi gerado, em dist\SofaHub.
  echo Para gerar o instalador:  winget install JRSoftware.InnoSetup
  goto :fim
)
%ISCC% /Q /DAppVersion=%VERSAO% instalador\SofaHub.iss || goto :erro
echo.
echo Pronto: instalador\Output\SofaHub-Setup-%VERSAO%.exe
goto :fim

:erro
echo.
echo ERRO - veja as mensagens acima.
:fim
pause
