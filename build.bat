@echo off
REM build.bat  —  Full Vibechecker Windows build pipeline
REM
REM Prerequisites:
REM   - 64-bit Python 3.10+ in PATH (recommend pyenv-win or official installer)
REM   - pip install pyinstaller
REM   - PicoSDK installed (for DLL collection step)
REM   - Inno Setup 6.x installed (iscc.exe in PATH or default location)
REM
REM Usage:
REM   build.bat            — full build: DLLs + PyInstaller + Inno Setup
REM   build.bat pyinstaller — PyInstaller only (skip DLL collection)
REM   build.bat installer   — Inno Setup only (requires dist\ to exist)

setlocal enabledelayedexpansion

set "STEP=%1"
set "ISCC= %APPDATA%\..\Local\Programs\Inno Setup 6\ISCC.exe"

echo.
echo ============================================================
echo   Vibechecker Windows Build Pipeline
echo ============================================================
echo.

REM ── Step 1: Collect PicoScope DLLs ──────────────────────────────────────────
if "%STEP%"=="" goto :collect_dlls
if /i "%STEP%"=="dlls" goto :collect_dlls
goto :pyinstaller

:collect_dlls
echo [1/3] Collecting PicoScope DLLs...
python build\collect_pico_dlls.py
if errorlevel 1 (
    echo ERROR: DLL collection failed. Ensure PicoSDK is installed.
    exit /b 1
)
echo.

REM ── Step 2: PyInstaller ─────────────────────────────────────────────────────
:pyinstaller
if /i "%STEP%"=="installer" goto :inno_setup
echo [2/3] Building executable with PyInstaller...
pyinstaller vibechecker.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
echo.

REM ── Step 3: Inno Setup ──────────────────────────────────────────────────────
:inno_setup
echo [3/3] Creating installer with Inno Setup...
if not exist "%ISCC%" (
    echo WARNING: iscc.exe not found at "%ISCC%"
    echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo or run manually: iscc installer\vibechecker.iss
    goto :done
)
"%ISCC%" installer\vibechecker.iss
if errorlevel 1 (
    echo ERROR: Inno Setup failed.
    exit /b 1
)

:done
echo.
echo ============================================================
echo   Build complete.
echo   Installer: installer\Output\VibecheckerSetup-*.exe
echo ============================================================
endlocal
