@echo off
rem Windows: double-click to start the local web UI (webui design 3.2, 6.5). Keep this file ASCII with CRLF endings.
rem First sets up .venv with uv from the hash-pinned requirements.lock; a missing font is explained on the page.
rem Every error ends in pause: a double-clicked window closes as soon as the script ends.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || goto not_repo
if not exist "scripts\webui.py" goto not_repo
set "VENV_PYTHON=.venv\Scripts\python.exe"

rem Ready: .venv has its interpreter and a copy of the requirements.lock it was installed from. The copy is written
rem after a good install, so an interrupted install or a lock changed by git pull installs again.
if not exist "%VENV_PYTHON%" goto setup
fc /b "requirements.lock" ".venv\requirements.lock" >nul 2>&1 || goto setup
goto launch

:setup
where uv >nul 2>&1 || goto no_uv
if exist "%VENV_PYTHON%" goto reinstall
echo Setting up the Python environment .venv with uv.
echo The first run downloads about 280-390 MiB of packages and takes a few minutes.
if exist ".venv" rmdir /s /q ".venv"
set "SETUP_LOG=%TEMP%\tissueplate-uv-venv.log"
set "VENV_FAILED="
rem call: a uv.bat / uv.cmd shim (pyenv-win, mise) would otherwise end this script when it ends
call uv venv --python 3.12 .venv >"%SETUP_LOG%" 2>&1 || set "VENV_FAILED=1"
type "%SETUP_LOG%"
set "HIT_448="
findstr /c:"os error 448" <"%SETUP_LOG%" >nul 2>&1 && set "HIT_448=1"
del "%SETUP_LOG%" >nul 2>&1
if not defined VENV_FAILED goto install
if defined HIT_448 goto venv_448
goto venv_failed

:venv_448
rem uv reaches its Python 3.12 through a directory junction that this Windows does not trust (os error 448).
rem Fallback: the standard library venv of that Python's real folder, which uv venv has just found or downloaded,
rem then the same install. Tried on one machine only.
rem The folder is uv's default or UV_PYTHON_INSTALL_DIR, not the output of uv python dir: for /f decodes that UTF-8
rem output with the console code page and would garble a non-ASCII user folder. The default follows uv-state:
rem APPDATA\uv\data\python when an older uv made APPDATA\uv\data, else APPDATA\uv\python.
echo uv venv hit os error 448: trying the standard library venv of uv's own Python 3.12 instead.
if exist ".venv" rmdir /s /q ".venv"
set "MANAGED_DIR=%APPDATA%\uv\python"
if exist "%APPDATA%\uv\data\" set "MANAGED_DIR=%APPDATA%\uv\data\python"
if defined UV_PYTHON_INSTALL_DIR set "MANAGED_DIR=%UV_PYTHON_INSTALL_DIR%"
if not exist "%MANAGED_DIR%\" goto no_managed_dir
rem cpython-3.12-* is the junction (a reparse point), the cpython-3.12.N-* folder next to it is the real one; with
rem several patch versions this takes the last by name (3.12.9 after 3.12.12), still a working 3.12
set "MANAGED_NAME="
for /f "delims=" %%N in ('dir /b /ad-l "%MANAGED_DIR%\cpython-3.12*" 2^>nul') do set "MANAGED_NAME=%%N"
if not defined MANAGED_NAME goto no_real_python
"%MANAGED_DIR%\%MANAGED_NAME%\python.exe" -I -m venv .venv || goto stdlib_venv_failed
goto install

:no_managed_dir
echo The folder of uv's own Pythons does not exist: "%MANAGED_DIR%".
goto managed_dir_hint

:no_real_python
echo No real cpython-3.12* folder (one that is not a directory junction) in "%MANAGED_DIR%".

:managed_dir_hint
echo If "uv python dir" prints another folder: set UV_PYTHON_INSTALL_DIR to it in a Command Prompt and run
echo start-webui.cmd from there.
goto venv_failed

:stdlib_venv_failed
echo The standard library venv of "%MANAGED_DIR%\%MANAGED_NAME%\python.exe" failed.
goto venv_failed

:reinstall
echo The packages in .venv do not match requirements.lock: the repository was updated or an install did not finish.
echo Installing them again.

:install
call uv pip install --python "%VENV_PYTHON%" --require-hashes -r requirements.lock || goto install_failed
copy /y "requirements.lock" ".venv\requirements.lock" >nul || goto copy_failed

:launch
rem Success and failure both end on the server line: cmd reads this file again after a command, so a git pull
rem while the server ran (often for hours) would otherwise make it run whatever line now sits at the old offset.
"%VENV_PYTHON%" -I -X utf8 -u scripts\webui.py %* && exit /b 0 || goto server_failed

:not_repo
echo start-webui.cmd has to stay in the repository folder, on a local drive: scripts\webui.py was not found.
goto failed

:no_uv
echo uv is needed once, to set up the Python environment. How to install it:
echo   https://docs.astral.sh/uv/getting-started/installation/
echo or with winget:  winget install --id=astral-sh.uv -e
echo Then close this window and double-click start-webui.cmd again.
goto failed

:venv_failed
echo Could not create the Python environment .venv, see the messages above.
echo On a slow or broken network just run this file again.
goto failed

:install_failed
echo Could not install the packages of requirements.lock, see the messages above.
echo On a slow or broken network just run this file again: finished downloads are kept.
goto failed

:copy_failed
echo The packages are installed, but requirements.lock could not be copied into .venv, see the message above.
echo Run this file again: it checks the packages once more and retries the copy.
goto failed

:server_failed
echo The web UI stopped with an error, see the messages above.
echo If Python itself did not start (for example, the Python that .venv was made from was uninstalled or moved),
echo delete the .venv folder and run this file again to set it up anew.

:failed
pause
exit /b 1
