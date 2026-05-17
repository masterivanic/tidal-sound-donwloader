@echo off
setlocal EnableDelayedExpansion

title FFmpeg Installer for Windows
echo ============================================
echo        FFmpeg Installer for Windows
echo ============================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] This script requires Administrator privileges.
    echo [!] Please right-click and select "Run as administrator".
    pause
    exit /b 1
)

:: Define paths
set "FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
set "DOWNLOAD_DIR=%TEMP%\ffmpeg_install"
set "FFMPEG_ZIP=%DOWNLOAD_DIR%\ffmpeg.zip"
set "EXTRACT_DIR=%DOWNLOAD_DIR%\extracted"
set "INSTALL_DIR=C:\ffmpeg"

echo [1/5] Checking dependencies...

:: Check if ffmpeg already installed
where ffmpeg >nul 2>&1
if %errorLevel% equ 0 (
    echo [*] FFmpeg is already installed and on PATH.
    ffmpeg -version 2>&1 | findstr "ffmpeg version"
    echo.
    choice /C YN /M "Reinstall anyway?"
    if !errorLevel! equ 2 goto :done
)

:: Check PowerShell availability
powershell -Command "exit 0" >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] PowerShell is required but not found.
    pause
    exit /b 1
)

echo [OK] Dependencies checked.
echo.

:: Create temp download directory
echo [2/5] Preparing download directory...
if exist "%DOWNLOAD_DIR%" rd /s /q "%DOWNLOAD_DIR%"
mkdir "%DOWNLOAD_DIR%"
mkdir "%EXTRACT_DIR%"
echo [OK] Directory: %DOWNLOAD_DIR%
echo.

:: Download ffmpeg zip via PowerShell
echo [3/5] Downloading FFmpeg (this may take a minute)...
echo      URL: %FFMPEG_URL%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
     $ProgressPreference = 'SilentlyContinue'; ^
     Write-Host '     Connecting...'; ^
     Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile '%FFMPEG_ZIP%' -UseBasicParsing; ^
     Write-Host '     Download complete.'"

if not exist "%FFMPEG_ZIP%" (
    echo [ERROR] Download failed. Check your internet connection.
    pause
    exit /b 1
)

:: Show file size
for %%A in ("%FFMPEG_ZIP%") do echo [OK] Downloaded: %%~zA bytes
echo.

:: Extract zip via PowerShell
echo [4/5] Extracting archive...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference = 'SilentlyContinue'; ^
     Expand-Archive -Path '%FFMPEG_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force; ^
     Write-Host '     Extraction complete.'"

if %errorLevel% neq 0 (
    echo [ERROR] Extraction failed.
    pause
    exit /b 1
)

:: Find the extracted ffmpeg folder (name varies by release)
set "FFMPEG_BIN="
for /d %%D in ("%EXTRACT_DIR%\ffmpeg-*") do (
    if exist "%%D\bin\ffmpeg.exe" (
        set "FFMPEG_BIN=%%D\bin"
    )
)

if "%FFMPEG_BIN%"=="" (
    echo [ERROR] Could not locate ffmpeg.exe in extracted archive.
    echo         Contents of extract dir:
    dir "%EXTRACT_DIR%" /b
    pause
    exit /b 1
)

echo [OK] Found binaries at: %FFMPEG_BIN%
echo.

:: Install to C:\ffmpeg
echo [5/5] Installing to %INSTALL_DIR%...

if exist "%INSTALL_DIR%" (
    echo      Removing old installation...
    rd /s /q "%INSTALL_DIR%"
)

mkdir "%INSTALL_DIR%\bin"
copy /Y "%FFMPEG_BIN%\ffmpeg.exe"  "%INSTALL_DIR%\bin\" >nul
copy /Y "%FFMPEG_BIN%\ffprobe.exe" "%INSTALL_DIR%\bin\" >nul
copy /Y "%FFMPEG_BIN%\ffplay.exe"  "%INSTALL_DIR%\bin\" >nul 2>&1

if not exist "%INSTALL_DIR%\bin\ffmpeg.exe" (
    echo [ERROR] Failed to copy files to %INSTALL_DIR%\bin
    pause
    exit /b 1
)

echo [OK] Files copied to %INSTALL_DIR%\bin
echo.

:: Add to system PATH permanently
echo Adding to system PATH...

:: Read current system PATH
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "CURRENT_PATH=%%B"

:: Check if already in PATH
echo !CURRENT_PATH! | findstr /I /C:"%INSTALL_DIR%\bin" >nul
if %errorLevel% equ 0 (
    echo [*] Already in system PATH, skipping.
) else (
    :: Append to system PATH via registry
    reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" ^
        /v Path /t REG_EXPAND_SZ /d "!CURRENT_PATH!;%INSTALL_DIR%\bin" /f >nul
    if %errorLevel% equ 0 (
        echo [OK] Added to system PATH.
    ) else (
        echo [WARN] Could not update system PATH via registry.
        echo        You may need to add manually: %INSTALL_DIR%\bin
    )
)

:: Also set for current session
set "PATH=%PATH%;%INSTALL_DIR%\bin"

:: Broadcast WM_SETTINGCHANGE so Explorer picks up new PATH
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[System.Environment]::SetEnvironmentVariable('Path', [System.Environment]::GetEnvironmentVariable('Path','Machine'), 'Machine')" >nul 2>&1

echo.

:: Verify installation
echo ============================================
echo              Verifying install
echo ============================================
"%INSTALL_DIR%\bin\ffmpeg.exe" -version 2>&1 | findstr "ffmpeg version"
if %errorLevel% equ 0 (
    echo.
    echo [SUCCESS] FFmpeg is installed correctly!
) else (
    echo [WARN] Verification failed — try opening a new terminal and running: ffmpeg -version
)

:: Cleanup temp files
echo.
echo Cleaning up temporary files...
rd /s /q "%DOWNLOAD_DIR%" >nul 2>&1
echo [OK] Done.

:done
echo.
echo ============================================
echo  FFmpeg installed to : %INSTALL_DIR%\bin
echo  Executables         : ffmpeg.exe, ffprobe.exe, ffplay.exe
echo.
echo  NOTE: Open a NEW terminal window for PATH
echo        changes to take effect.
echo ============================================
echo.
pause