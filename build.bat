@echo off
setlocal enabledelayedexpansion

set "APP_NAME=EkilaDownAudio"
set "BUILDER_ROOT=%~dp0"
set "ROOT_MAIN=%BUILDER_ROOT%main.py"


:: Force admin elevation
NET FILE >nul 2>&1
if not %errorlevel% == 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -Wait -Verb RunAs cmd -ArgumentList '/c \"%~f0\"'"
    exit /b
)


echo Installing Python requirements...
pip install --upgrade pip
pip install -r "%BUILDER_ROOT%requirements.txt"


echo Running root install.bat (FFmpeg / pre‑install)...
if exist "%BUILDER_ROOT%install.bat" (
    pushd "%BUILDER_ROOT%"
    call "%BUILDER_ROOT%install.bat"
    popd
)


:: ONLY build from the root main.py
if not exist "%ROOT_MAIN%" (
    echo ERROR: main.py not found in root: %ROOT_MAIN%
    pause
    exit /b
)

echo Building EkilaDownAudio executable from %ROOT_MAIN%...

if exist "%BUILDER_ROOT%build" rmdir /s /q "%BUILDER_ROOT%build"
if exist "%BUILDER_ROOT%dist" rmdir /s /q "%BUILDER_ROOT%dist"

python -m pip install pyinstaller

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --uac-admin ^
    --name "%APP_NAME%" ^
    "%ROOT_MAIN%"

echo Build and installer logic complete.
echo Your app is at: %BUILDER_ROOT%dist\%APP_NAME%.exe
pause
endlocal