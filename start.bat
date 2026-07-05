@echo off
REM ============================================================
REM   Ahmed Poly Bags — full-fledged self-bootstrapping launcher
REM   v5 — self-update from GitHub Releases + DB migrations
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Ahmed Poly Bags

set "LOG=%~dp0start.log"
set "PY_EXE="
set "PY_ARGS="
set "PY_VER="
set "PORT=8003"

REM ── GitHub self-update config ──
set "GH_REPO=muhammadiibrahiim/wealth-tracker"
set "ASSET_NAME=Ahmed-Poly-Bags-app.zip"

REM ── Fresh log for each run ──
echo. > "%LOG%"
call :say "============================================================"
call :say "  Ahmed Poly Bags — launcher v5"
call :say "  Started at !DATE! !TIME!"
call :say "  Script dir: %~dp0"
call :say "  User: !USERNAME!    Computer: !COMPUTERNAME!"
call :say "  Log:  %LOG%"
call :say "============================================================"
call :say ""

REM =============================================================
REM   Phase 0: check GitHub for a newer release, self-update
REM =============================================================
call :phase_selfupdate

REM =============================================================
REM   Phase 1: environment probe (all logged for remote debug)
REM =============================================================
call :say "[Phase 1/7] Environment probe"
call :say "  OS:            !OS!"
call :say "  ARCH:          !PROCESSOR_ARCHITECTURE!"
call :say "  USERPROFILE:   !USERPROFILE!"
call :say "  LOCALAPPDATA:  !LOCALAPPDATA!"
call :say "  Current dir:   %CD%"
ver >> "%LOG%" 2>&1

REM ── Fast-path: existing venv? just activate + skip Python detection ──
if exist "venv\Scripts\python.exe" (
    call :say ""
    call :say "[Phase 2/7] Existing venv found — activating"
    call "venv\Scripts\activate.bat"
    call :say "  [OK] activated"
    goto :phase_migrate
)

REM =============================================================
REM   Phase 2: find a working Python 3 (7 methods)
REM =============================================================
call :say ""
call :say "[Phase 2/7] Searching for Python 3..."

REM ── Method 1: py -3 launcher ──
call :try_py_launcher

REM ── Method 2: plain "python" on PATH ──
if not defined PY_EXE call :try_python_on_path python
if not defined PY_EXE call :try_python_on_path python3

REM ── Method 3: standard install directories (all major Python versions) ──
if not defined PY_EXE (
    call :say "  Method 3: scanning standard install directories"
    REM 3.13/3.12/3.11 first — proven to have wheels for all our deps.
    REM 3.14 last — some packages don't ship 3.14 wheels yet.
    for %%V in (313 312 311 310 39 38 37 314) do (
        if not defined PY_EXE (
            call :probe_path "!LOCALAPPDATA!\Programs\Python\Python%%V\python.exe"
            call :probe_path "!USERPROFILE!\AppData\Local\Programs\Python\Python%%V\python.exe"
            call :probe_path "C:\Program Files\Python%%V\python.exe"
            call :probe_path "C:\Program Files (x86)\Python%%V\python.exe"
            call :probe_path "C:\Python%%V\python.exe"
            call :probe_path "D:\Python%%V\python.exe"
        )
    )
)

REM ── Method 4: Anaconda / Miniconda ──
if not defined PY_EXE (
    call :say "  Method 4: scanning Anaconda / Miniconda locations"
    call :probe_path "!USERPROFILE!\anaconda3\python.exe"
    call :probe_path "!USERPROFILE!\miniconda3\python.exe"
    call :probe_path "!USERPROFILE!\Anaconda3\python.exe"
    call :probe_path "!USERPROFILE!\Miniconda3\python.exe"
    call :probe_path "C:\ProgramData\Anaconda3\python.exe"
    call :probe_path "C:\ProgramData\Miniconda3\python.exe"
)

REM ── Method 5: Windows registry ──
if not defined PY_EXE (
    call :say "  Method 5: querying Windows registry"
    for /f "usebackq skip=2 tokens=3*" %%A in (`reg query "HKLM\SOFTWARE\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"`) do (
        call :probe_path "%%A%%B\python.exe"
    )
    for /f "usebackq skip=2 tokens=3*" %%A in (`reg query "HKCU\SOFTWARE\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"`) do (
        call :probe_path "%%A%%B\python.exe"
    )
    for /f "usebackq skip=2 tokens=3*" %%A in (`reg query "HKLM\SOFTWARE\Wow6432Node\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"`) do (
        call :probe_path "%%A%%B\python.exe"
    )
)

REM ── Method 6: Microsoft Store non-alias install (if user got it from Store) ──
if not defined PY_EXE (
    call :say "  Method 6: scanning Windows Apps folder"
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python*") do (
        call :probe_path "%%D\python.exe"
    )
)

REM ── Method 7: any python.exe anywhere on PATH we haven't tried ──
if not defined PY_EXE (
    call :say "  Method 7: exhaustive PATH scan"
    for %%D in ("%PATH:;=" "%") do (
        if not defined PY_EXE (
            call :probe_path "%%~D\python.exe"
            call :probe_path "%%~D\python3.exe"
        )
    )
)

if defined PY_EXE goto :python_ok

REM =============================================================
REM   Python not found — offer winget install, else diagnostic
REM =============================================================
call :say ""
call :say "[X] Could not find any working Python 3 on this computer."
call :say ""

where winget >nul 2>&1
if !errorlevel! equ 0 (
    call :say "  winget is available — auto-installing Python 3.12."
    call :say "  This is a one-time download of ~30 MB. Please wait 1-3 minutes."
    call :say "  Running: winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements"
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements 2>>"%LOG%"
    if !errorlevel! equ 0 (
        call :say "  [OK] Python 3.12 installed via winget."
        call :say ""
        call :say "  Re-scanning for the new Python installation..."
        REM winget put Python in %LOCALAPPDATA%\Programs\Python\Python312 — probe it directly.
        call :probe_path "!LOCALAPPDATA!\Programs\Python\Python312\python.exe"
        call :probe_path "C:\Program Files\Python312\python.exe"
        REM Try the py launcher too (installed alongside)
        if not defined PY_EXE call :try_py_launcher
        if defined PY_EXE (
            call :say "  [OK] found Python — continuing without a restart."
            call :say ""
            goto :python_ok
        )
        REM Fallback: PATH isn't refreshed for this cmd, so ask the user to relaunch.
        call :say ""
        call :say "  Python is installed but this Command Prompt started before"
        call :say "  the install, so it can't see the new PATH yet."
        call :say "  Close this window and double-click start.bat again."
        call :say ""
        pause
        exit /b 0
    )
    call :say "  [X] winget install failed — see start.log. Falling back to manual instructions."
)

call :show_manual_help
exit /b 1

:python_ok
call :say ""
call :say "  [OK] Selected Python:"
call :say "       !PY_EXE! !PY_ARGS!"
"%PY_EXE%" %PY_ARGS% --version > "%TEMP%\py_ver.tmp" 2>&1
set /p PY_VER=<"%TEMP%\py_ver.tmp"
del "%TEMP%\py_ver.tmp" >nul 2>&1
call :say "       !PY_VER!"
echo !PY_VER! | findstr /c:"3.14" >nul
if !errorlevel! equ 0 (
    call :say ""
    call :say "  NOTE: Python 3.14 is very new. Some packages may need extra"
    call :say "        time to install. If the install step fails complaining"
    call :say "        about 'building wheel' or 'rustc' or 'link.exe', it"
    call :say "        means a package needs Python 3.12 instead. Install"
    call :say "        Python 3.12 from python.org and re-run start.bat."
    call :say ""
)

REM =============================================================
REM   Phase 3: verify Python is fit for purpose (>= 3.9, has pip/venv)
REM =============================================================
call :say ""
call :say "[Phase 3/7] Validating Python..."
"%PY_EXE%" %PY_ARGS% -c "import sys; assert sys.version_info >= (3, 9), f'Need Python 3.9+, got {sys.version}'" 2>>"%LOG%"
if !errorlevel! neq 0 (
    call :say "  [X] Python version is too old. Need 3.9 or newer, got !PY_VER!"
    call :show_manual_help
    exit /b 1
)
call :say "  [OK] version >= 3.9"

"%PY_EXE%" %PY_ARGS% -c "import ensurepip" 2>>"%LOG%"
if !errorlevel! neq 0 call :say "  WARN: ensurepip is missing — will try anyway"
"%PY_EXE%" %PY_ARGS% -c "import venv" 2>>"%LOG%"
if !errorlevel! neq 0 (
    call :say "  [X] Python's venv module is not available."
    call :say "      On Ubuntu/Debian: sudo apt install python3-venv"
    call :say "      On Windows: reinstall Python from python.org"
    call :show_manual_help
    exit /b 1
)
call :say "  [OK] venv module available"

REM =============================================================
REM   Phase 4: create virtual environment
REM =============================================================
call :say ""
call :say "[Phase 4/7] Creating virtual environment (.\venv)..."
call :say "  Running: !PY_EXE! !PY_ARGS! -m venv venv"
"%PY_EXE%" %PY_ARGS% -m venv venv >>"%LOG%" 2>&1
if !errorlevel! equ 0 (
    call :say "  [OK] venv created"
) else (
    call :say "  venv create failed — retry with --without-pip..."
    "%PY_EXE%" %PY_ARGS% -m venv --without-pip venv >>"%LOG%" 2>&1
    if !errorlevel! equ 0 (
        call :say "  [OK] venv created without pip; bootstrapping pip..."
        call "venv\Scripts\activate.bat"
        python -m ensurepip --upgrade >>"%LOG%" 2>&1
        if !errorlevel! neq 0 (
            call :say "  [X] Could not bootstrap pip. Aborting."
            call :dump_log_tail
            exit /b 1
        )
    ) else (
        call :say "  [X] venv creation failed both ways."
        call :dump_log_tail
        call :show_manual_help
        exit /b 1
    )
)

call "venv\Scripts\activate.bat"

REM =============================================================
REM   Phase 5: install required packages
REM =============================================================
:phase_packages
call :say ""
call :say "[Phase 5/7] Checking required packages..."
python -c "import uvicorn, fastapi, sqlmodel, jinja2, alembic, multipart, reportlab, dateutil, pydantic, sqlalchemy" >nul 2>&1
if !errorlevel! equ 0 (
    call :say "  [OK] all required packages already installed"
    goto :phase_launch
)

call :say "  Not all packages present — installing..."
call :say ""
call :say "  Step 5a: upgrading pip..."
python -m pip install --upgrade pip >>"%LOG%" 2>&1
if !errorlevel! equ 0 (
    call :say "  [OK] pip upgraded"
) else (
    call :say "  WARN: pip upgrade failed (continuing anyway)"
)

call :say ""
call :say "  Step 5b: installing requirements.txt (this takes 1–2 minutes)..."
python -m pip install -r requirements.txt
if !errorlevel! equ 0 goto :packages_ok

call :say ""
call :say "  Bulk install failed. Retrying with --no-cache-dir..."
python -m pip install --no-cache-dir -r requirements.txt
if !errorlevel! equ 0 goto :packages_ok

call :say ""
call :say "  Still failing. Installing packages one-by-one so we can"
call :say "  see which one is the problem..."
call :pip_one "fastapi==0.109.0"
call :pip_one "uvicorn[standard]==0.27.0"
call :pip_one "sqlmodel==0.0.14"
call :pip_one "pydantic==2.10.4"
call :pip_one "SQLAlchemy==2.0.50"
call :pip_one "alembic==1.13.1"
call :pip_one "jinja2==3.1.3"
call :pip_one "python-multipart==0.0.6"
call :pip_one "python-dateutil"
call :pip_one "reportlab==4.0.9"

python -c "import uvicorn, fastapi, sqlmodel, jinja2, alembic, multipart, reportlab, dateutil, pydantic, sqlalchemy" >nul 2>&1
if !errorlevel! neq 0 (
    call :say ""
    call :say "  [X] Package installation could not complete."
    call :say "      Most likely cause: no internet connection,"
    call :say "      or a corporate firewall is blocking pypi.org."
    call :dump_log_tail
    call :show_manual_help
    exit /b 1
)

:packages_ok
call :say "  [OK] all packages installed"

REM =============================================================
REM   Phase 6: backup DB + run alembic migrations
REM =============================================================
:phase_migrate
call :say ""
call :say "[Phase 6/7] Database backup + migrations..."
if exist "wealth_tracker.db" (
    if not exist "backups" mkdir backups
    REM Build a filesystem-safe timestamp: YYYY-MM-DD_HH-MM
    for /f "tokens=1-3 delims=/-. " %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm"') do set "TS=%%a"
    set "BACKUP=backups\wealth_tracker.db.!TS!.bak"
    copy /Y wealth_tracker.db "!BACKUP!" >nul 2>&1
    if !errorlevel! equ 0 (
        call :say "  [OK] backed up DB to !BACKUP!"
    ) else (
        call :say "  WARN: DB backup failed — proceeding anyway"
    )
    REM Prune backups older than 30 days (keep the folder tidy)
    forfiles /P backups /M "wealth_tracker.db.*.bak" /D -30 /C "cmd /c del @path" >nul 2>&1
) else (
    call :say "  (no existing DB — will be created by migrations)"
)

if exist "alembic.ini" (
    call :say "  Running: alembic upgrade head"
    python -m alembic upgrade head >>"%LOG%" 2>&1
    if !errorlevel! neq 0 (
        call :say "  [X] alembic migration failed — see start.log"
        call :dump_log_tail
        if exist "!BACKUP!" (
            call :say ""
            call :say "  Your DB was backed up before this attempt:"
            call :say "     !BACKUP!"
            call :say "  If the app misbehaves, close this window and restore"
            call :say "  that file over wealth_tracker.db to roll back."
        )
        pause
        exit /b 1
    )
    call :say "  [OK] schema up to date"
) else (
    call :say "  (no alembic.ini — skipping migrations)"
)

REM =============================================================
REM   Phase 7: launch the app
REM =============================================================
:phase_launch
call :say ""
call :say "[Phase 7/7] Launching app..."

REM ── Port probe: prefer 8003, but fall back to 8004..8010 if in use ──
call :say "  Checking port !PORT!..."
netstat -ano | findstr /r /c:":!PORT! .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    call :say "  Port !PORT! is busy — searching for a free one..."
    for %%P in (8004 8005 8006 8007 8008 8009 8010 9000) do (
        if "!PORT!"=="8003" (
            netstat -ano | findstr /r /c:":%%P .*LISTENING" >nul 2>&1
            if !errorlevel! neq 0 (
                set "PORT=%%P"
                call :say "  Using port %%P instead."
            )
        )
    )
)
call :say "  Port: !PORT!"
call :say ""
call :say "============================================================"
call :say "  Ahmed Poly Bags is starting on:"
call :say "     http://localhost:!PORT!"
call :say "  A browser tab will open in a few seconds."
call :say "  Keep this window open. Press Ctrl+C to stop the server."
call :say "============================================================"
call :say ""

start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:!PORT!"
python -m uvicorn main:app --port !PORT!

call :say ""
call :say "Server stopped at !DATE! !TIME!"
call :say "(log at %LOG%)"
pause
exit /b 0

REM ─────────────────────────────────────────────────────────────
REM   Subroutines

:phase_selfupdate
REM Check GitHub Releases API for a newer version and apply it.
REM Fails silently on no internet / no releases — never blocks startup.
call :say "[Phase 0/7] Checking for updates from GitHub..."

REM Read local version (created by the release CI, or missing on very first run)
if exist "version.txt" (
    set /p LOCAL_VERSION=<version.txt
) else (
    set "LOCAL_VERSION=none"
)
call :say "  Current version: !LOCAL_VERSION!"

REM Query GitHub for the latest release tag
for /f "delims=" %%v in ('powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/%GH_REPO%/releases/latest' -Headers @{ 'User-Agent' = 'wealth-tracker-launcher' }; $r.tag_name } catch { '' }" 2^>nul') do set "LATEST_VERSION=%%v"

if not defined LATEST_VERSION (
    call :say "  (no releases yet or offline — skipping update)"
    call :say ""
    goto :eof
)
call :say "  Latest release:  !LATEST_VERSION!"

if "!LOCAL_VERSION!"=="!LATEST_VERSION!" (
    call :say "  [OK] you are up to date"
    call :say ""
    goto :eof
)

call :say "  Update available — downloading !LATEST_VERSION!..."
set "UPDATE_ZIP=%TEMP%\ahmed_update_%RANDOM%.zip"
set "UPDATE_DIR=%TEMP%\ahmed_update_%RANDOM%"
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://github.com/%GH_REPO%/releases/latest/download/%ASSET_NAME%' -OutFile '%UPDATE_ZIP%' -UseBasicParsing -UserAgent 'wealth-tracker-launcher' } catch { exit 1 }" 2>>"%LOG%"
if !errorlevel! neq 0 (
    call :say "  [X] download failed — continuing with current version"
    call :say ""
    goto :eof
)

call :say "  Extracting..."
powershell -NoProfile -Command "try { Expand-Archive -Path '%UPDATE_ZIP%' -DestinationPath '%UPDATE_DIR%' -Force } catch { exit 1 }" 2>>"%LOG%"
if !errorlevel! neq 0 (
    call :say "  [X] extract failed — continuing with current version"
    del "%UPDATE_ZIP%" >nul 2>&1
    call :say ""
    goto :eof
)

REM The zip contains "Ahmed Poly Bags\<files>" at the top level.
REM Robocopy everything to the current dir, but PRESERVE the user's data:
REM  - wealth_tracker.db (their real trades)
REM  - venv\ (their installed packages)
REM  - backups\ (their DB snapshots)
REM  - start.log (this session's log)
call :say "  Applying update (preserving your data)..."
robocopy "%UPDATE_DIR%\Ahmed Poly Bags" "%~dp0." /E /XF wealth_tracker.db start.log /XD venv .venv backups /NFL /NDL /NJH /NJS /R:1 /W:1 >>"%LOG%" 2>&1
REM robocopy returns 0-7 as success codes; only >=8 is a real error
if !errorlevel! geq 8 (
    call :say "  [X] robocopy failed — see start.log"
    rmdir /S /Q "%UPDATE_DIR%" >nul 2>&1
    del "%UPDATE_ZIP%" >nul 2>&1
    call :say ""
    goto :eof
)

rmdir /S /Q "%UPDATE_DIR%" >nul 2>&1
del "%UPDATE_ZIP%" >nul 2>&1
call :say "  [OK] updated to !LATEST_VERSION!"
call :say ""
goto :eof

REM ─────────────────────────────────────────────────────────────

:say
REM Log a line to both console and file with timestamp
echo %~1
echo [!TIME!] %~1 >> "%LOG%"
goto :eof

:try_py_launcher
where py >nul 2>&1
if !errorlevel! neq 0 (
    call :say "  Method 1: py.exe launcher NOT on PATH"
    goto :eof
)
call :say "  Method 1: py.exe launcher is on PATH"
REM Prefer specific versions in this order — 3.13 → 3.12 → 3.11 are known to
REM have prebuilt wheels for every dep we use. 3.14 is bleeding-edge and some
REM packages don't ship wheels for it yet, so we only fall back to it last.
for %%V in (3.13 3.12 3.11 3.10 3) do (
    if not defined PY_EXE (
        call :say "    trying: py -%%V"
        py -%%V -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY_EXE=py"
            set "PY_ARGS=-%%V"
            call :say "    [OK] py -%%V works"
        )
    )
)
if defined PY_EXE goto :eof
call :say "    trying: py  (any version)"
py -c "import sys" >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_EXE=py"
    set "PY_ARGS="
    call :say "    [OK] py works"
)
goto :eof

:try_python_on_path
if defined PY_EXE goto :eof
where %~1 >nul 2>&1
if !errorlevel! neq 0 (
    call :say "  Method 2: %~1 NOT on PATH"
    goto :eof
)
call :say "  Method 2: %~1 is on PATH — validating"
%~1 -c "import sys" >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_EXE=%~1"
    set "PY_ARGS="
    call :say "    [OK] %~1 works"
) else (
    call :say "    [X] %~1 is on PATH but does not run — probably the Store stub"
)
goto :eof

:probe_path
if defined PY_EXE goto :eof
set "TEST_EXE=%~1"
if not exist "!TEST_EXE!" goto :eof
call :say "    testing: !TEST_EXE!"
"!TEST_EXE!" -c "import sys" >nul 2>&1
if !errorlevel! equ 0 (
    set "PY_EXE=!TEST_EXE!"
    set "PY_ARGS="
    call :say "    [OK] works"
) else (
    call :say "    (present but doesn't run)"
)
goto :eof

:pip_one
call :say "    installing %~1..."
python -m pip install %1 >>"%LOG%" 2>&1
if !errorlevel! neq 0 (
    call :say "    [X] failed on %~1  (see start.log)"
) else (
    call :say "    [OK] %~1"
)
goto :eof

:dump_log_tail
echo.
echo --- last 20 lines of start.log ---
powershell -NoProfile -Command "Get-Content -Path '%LOG%' -Tail 20" 2>nul
echo ----------------------------------
echo.
goto :eof

:show_manual_help
echo.
echo ============================================================
echo   MANUAL FIX INSTRUCTIONS
echo ============================================================
echo.
echo   FIX A — Install Python from python.org
echo   ---------------------------------------
echo   1. Open  https://www.python.org/downloads/
echo   2. Download Python 3.12 or newer
echo   3. Run the installer. ON THE FIRST SCREEN:
echo        [X] Add python.exe to PATH        (small box at BOTTOM)
echo        [X] py launcher                    (already ticked usually)
echo   4. Click "Install Now" and wait
echo   5. CLOSE every Command Prompt window
echo   6. RESTART the PC once
echo   7. Double-click start.bat again
echo.
echo   FIX B — Disable Microsoft Store Python stubs
echo   --------------------------------------------
echo   1. Windows Settings
echo   2. Apps  ^>  Advanced app settings
echo   3. App execution aliases
echo   4. Turn OFF both:
echo         - python.exe
echo         - python3.exe
echo.
echo   FIX C — Uninstall Windows Store Python (recommended)
echo   ----------------------------------------------------
echo   1. Windows Settings  ^>  Apps
echo   2. Find "Python 3.x" (from Microsoft Store) and uninstall
echo   3. Then do FIX A
echo.
echo   FIX D — Send us the log
echo   ------------------------
echo   The file start.log next to start.bat has every step of
echo   what was tried. Send that file to Ibrahim and he can
echo   tell you exactly what needs to change.
echo.
echo ============================================================
echo   Press any key to close this window.
echo ============================================================
pause >nul
goto :eof
