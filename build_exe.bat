@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "APP_NAME=TraceAnalyzer"
set "ENTRY_FILE=main.py"
set "REQ_FILE=requirements-build.txt"
set "VENV_DIR=.build_venv"
set "PY_EXE=%VENV_DIR%\Scripts\python.exe"
set "PY_BASE="
set "BUILD_PY="
set "ONEFILE_FLAG="

if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--onefile" set "ONEFILE_FLAG=--onefile"

if not "%~1"=="" if /I not "%~1"=="--onefile" (
    echo [ERROR] Unknown option: %~1
    echo.
    goto :usage_error
)

if not exist "%ENTRY_FILE%" (
    echo [ERROR] Entry file not found: %ENTRY_FILE%
    exit /b 1
)

if not exist "%REQ_FILE%" (
    echo [ERROR] Dependency file not found: %REQ_FILE%
    exit /b 1
)

echo [1/5] Prepare isolated build environment...
if exist "%PY_EXE%" (
    "%PY_EXE%" -m pip --version >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "BUILD_PY=%PY_EXE%"
        goto :python_ready
    )
    echo [WARN] Existing %VENV_DIR% is incomplete ^(pip missing^). Recreating...
    rmdir /s /q "%VENV_DIR%"
)

if exist "venv\Scripts\python.exe" (
    set "PY_BASE=%cd%\venv\Scripts\python.exe"
)

if not defined PY_BASE (
    for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do (
        if not defined PY_BASE set "PY_BASE=%%I"
    )
)

if not defined PY_BASE (
    for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do (
        if not defined PY_BASE set "PY_BASE=%%I"
    )
)

if not defined PY_BASE (
    echo [ERROR] Python 3.10+ was not found in PATH.
    echo         Checked:
    echo         - venv\Scripts\python.exe
    echo         - py -3
    echo         - python
    echo         Install Python, then re-run this script.
    exit /b 1
)

echo         Base Python: %PY_BASE%
"%PY_BASE%" -m venv "%VENV_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Failed to create %VENV_DIR%, fallback to base Python.
    set "BUILD_PY=%PY_BASE%"
    goto :python_ready
)

if exist "%PY_EXE%" (
    set "BUILD_PY=%PY_EXE%"
) else (
    echo [WARN] %VENV_DIR% created but interpreter missing, fallback to base Python.
    set "BUILD_PY=%PY_BASE%"
)

:python_ready
"%BUILD_PY%" -c "import sys" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Selected Python is not runnable: %BUILD_PY%
    exit /b 1
)

set "FALLBACK_PY=%cd%\venv\Scripts\python.exe"
"%BUILD_PY%" -m pip --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] pip missing for: %BUILD_PY%
    echo        Trying ensurepip...
    "%BUILD_PY%" -m ensurepip --upgrade >nul 2>nul
    "%BUILD_PY%" -m pip --version >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        if /I not "%BUILD_PY%"=="%FALLBACK_PY%" if exist "%FALLBACK_PY%" (
            echo [WARN] Fallback to existing project venv Python.
            set "BUILD_PY=%FALLBACK_PY%"
        )
    )
)

"%BUILD_PY%" -m pip --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip is unavailable for selected Python: %BUILD_PY%
    exit /b 1
)

echo [2/5] Install or update packaging dependencies...
call :check_deps
if %ERRORLEVEL% EQU 0 goto :deps_ready

echo [INFO] Missing packages: %MISSING_DEPS%
echo        Trying to install from %REQ_FILE% ...
"%BUILD_PY%" -m pip install --disable-pip-version-check -r "%REQ_FILE%"

call :check_deps
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Required packages are still missing: %MISSING_DEPS%
    echo         If your machine is offline, install wheels first, then run again.
    exit /b 1
)

:deps_ready

echo [3/5] Clean previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%APP_NAME%.spec" del /f /q "%APP_NAME%.spec"

echo [4/5] Build executable with PyInstaller...
"%BUILD_PY%" -m PyInstaller --noconfirm --clean --windowed --name "%APP_NAME%" --collect-all PySide6 %ONEFILE_FLAG% "%ENTRY_FILE%"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [5/5] Build completed.
if defined ONEFILE_FLAG (
    echo Output: dist\%APP_NAME%.exe
) else (
    echo Output directory: dist\%APP_NAME%\
    echo Executable: dist\%APP_NAME%\%APP_NAME%.exe
)
exit /b 0

:usage
echo Usage:
echo   build_exe.bat            ^(default: folder build, recommended^)
echo   build_exe.bat --onefile  ^(single-file exe^)
exit /b 0

:usage_error
echo Usage:
echo   build_exe.bat
echo   build_exe.bat --onefile
exit /b 1

:check_deps
set "MISSING_DEPS="
"%BUILD_PY%" -c "import PySide6" >nul 2>nul
if %ERRORLEVEL% NEQ 0 set "MISSING_DEPS=PySide6"

"%BUILD_PY%" -c "import PyInstaller" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    if defined MISSING_DEPS (
        set "MISSING_DEPS=%MISSING_DEPS%,PyInstaller"
    ) else (
        set "MISSING_DEPS=PyInstaller"
    )
)

if defined MISSING_DEPS exit /b 1
exit /b 0
