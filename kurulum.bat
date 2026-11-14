@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo ==================================================
echo   EuroPulse RPC - ETS2 ^& Coaches DLC Kurulumu
echo ==================================================
echo.

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [HATA] Python 3 bulunamadi. Lutfen python.org uzerinden Python 3.10+ kurun.
        pause
        exit /b 1
    )
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY_EXE=%%I"
) else (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY_EXE=%%I"
)

for /f "delims=" %%I in ('"%PY_EXE%" -c "import os, sys; d=os.path.dirname(sys.executable); p=os.path.join(d, 'pythonw.exe'); print(p if os.path.exists(p) else sys.executable)"') do set "PYW_EXE=%%I"

echo [1/4] Python bagimliliklari yukleniyor...
"%PY_EXE%" -m pip install -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
    echo [HATA] Bagimliliklar yuklenemedi.
    pause
    exit /b 1
)

echo.
echo [2/4] Euro Truck Simulator 2 kurulum klasoru araniyor...
set "ETS2_DIR="
set "TMP_ETS2=%TEMP%\europulse_ets2_dir.txt"
if exist "%TMP_ETS2%" del /f /q "%TMP_ETS2%" >nul 2>&1
"%PY_EXE%" -c "import os, re, winreg; q = chr(34); b = chr(92); cands = []; exec('try:\n k=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r\'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Steam App 227300\')\n cands.append(winreg.QueryValueEx(k, \'InstallLocation\')[0])\nexcept OSError: pass'); exec('try:\n k=winreg.OpenKey(winreg.HKEY_CURRENT_USER, r\'Software\\Valve\\Steam\')\n sp=winreg.QueryValueEx(k, \'SteamPath\')[0].replace(\'/\', b)\n cands.append(os.path.join(sp, \'steamapps\', \'common\', \'Euro Truck Simulator 2\'))\n vdf=os.path.join(sp, \'steamapps\', \'libraryfolders.vdf\')\n if os.path.exists(vdf):\n  txt=open(vdf, encoding=\'utf-8\', errors=\'replace\').read()\n  for m in re.findall(q + \'path\' + q + \'\\\\s+\' + q + \'([^\' + q + \']+)\' + q, txt):\n   cands.append(os.path.join(m.replace(b*2, b), \'steamapps\', \'common\', \'Euro Truck Simulator 2\'))\nexcept OSError: pass'); cands.extend([d + r':\SteamLibrary\steamapps\common\Euro Truck Simulator 2' for d in 'CDEF'] + [d + r':\Program Files (x86)\Steam\steamapps\common\Euro Truck Simulator 2' for d in 'CDEF']); found = next((c for c in cands if c and os.path.exists(os.path.join(c, 'bin', 'win_x64', 'eurotrucks2.exe'))), ''); print(found, end='')" > "%TMP_ETS2%"
if exist "%TMP_ETS2%" (
    set /p ETS2_DIR=<"%TMP_ETS2%"
    del /f /q "%TMP_ETS2%" >nul 2>&1
)

if not defined ETS2_DIR (
    echo ETS2 kurulum klasoru otomatik bulunamadi.
    set /p "ETS2_DIR=Lutfen Euro Truck Simulator 2 ana klasor yolunu girin: "
)

if not exist "%ETS2_DIR%\bin\win_x64\eurotrucks2.exe" (
    echo [HATA] Belirtilen konumda bin\win_x64\eurotrucks2.exe bulunamadi: "%ETS2_DIR%"
    pause
    exit /b 1
)

echo ETS2 bulundu: "%ETS2_DIR%"
echo.
echo [3/4] scs-telemetry.dll eklentisi kopyalaniyor...
set "PLUGIN_DIR=%ETS2_DIR%\bin\win_x64\plugins"
if not exist "%PLUGIN_DIR%" mkdir "%PLUGIN_DIR%"
copy /y "%APP_DIR%\plugins\scs-telemetry.dll" "%PLUGIN_DIR%\scs-telemetry.dll" >nul
if errorlevel 1 (
    echo [HATA] scs-telemetry.dll kopyalanamadi. Oyun aciksa kapatip tekrar deneyin.
    pause
    exit /b 1
)

echo.
echo [4/4] Windows baslangic kaydi olusturuluyor ve arka plan servisi baslatiliyor...
set "STARTUP_VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ETS2_Discord_RPC.vbs"
> "%STARTUP_VBS%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%STARTUP_VBS%" echo WshShell.Run """%PYW_EXE%"" ""%APP_DIR%\ets2_rpc.py""", 0, False

powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*ets2_rpc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

wscript.exe "%STARTUP_VBS%"

echo.
echo ==================================================
echo   Kurulum tamamlandi! EuroPulse RPC arka planda
echo   sessizce calisiyor. Oyun aciksa bir kez yeniden
echo   baslatmaniz telemetry DLL'i aktif edecektir.
echo ==================================================
pause
