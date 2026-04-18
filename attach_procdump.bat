@echo off
REM Attach Microsoft ProcDump to the running python.exe so a minidump
REM (.dmp) is written to crash_logs\ on any first-chance exception,
REM unhandled exception, or process termination.  Use this ONLY when
REM faulthandler.log is empty for a silent crash — ProcDump captures
REM native C stacks (GPU driver, ffmpeg, pyglet C side) that Python
REM itself can't see.
REM
REM Setup (one time):
REM   1. Download ProcDump from https://docs.microsoft.com/sysinternals/downloads/procdump
REM   2. Extract procdump.exe somewhere on PATH, OR next to this .bat file.
REM
REM Usage:
REM   1. Launch the game:   python main.py
REM   2. In another shell:  attach_procdump.bat
REM   3. Reproduce the crash.  A .dmp file appears in crash_logs\.
REM   4. Open the .dmp in Visual Studio or WinDbg to see the C stack.
REM
REM The -ma flag writes full-memory dumps (bigger but usable).  Drop
REM to -mm for mini-dumps if disk space is tight.

setlocal
set "DUMP_DIR=%~dp0crash_logs"
if not exist "%DUMP_DIR%" mkdir "%DUMP_DIR%"

REM -e       first-chance unhandled exceptions
REM -t       process termination
REM -h       hang detection (no ping for >5s on UI thread)
REM -ma      full memory dump
REM -n 3     keep only last 3 dumps
procdump -accepteula -e -t -h -ma -n 3 python.exe "%DUMP_DIR%"

endlocal
