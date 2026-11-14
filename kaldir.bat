@echo off
chcp 65001 >nul
setlocal

echo ==================================================
echo   EuroPulse RPC - Arka Plan Servisini Kaldirma
echo ==================================================
echo.

echo [1/2] Calisan EuroPulse RPC sureci durduruluyor...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*ets2_rpc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Durduruldu PID: ' + $_.ProcessId) }"

echo [2/2] Windows baslangic kaydi temizleniyor...
set "STARTUP_VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ETS2_Discord_RPC.vbs"
if exist "%STARTUP_VBS%" (
    del /f /q "%STARTUP_VBS%"
    echo Baslangic dosyasi silindi: "%STARTUP_VBS%"
) else (
    echo Baslangic dosyasi zaten yok.
)

echo.
echo Kaldirma islemi tamamlandi.
echo Not: Isterseniz ETS2 klasorunuzdeki bin\win_x64\plugins\scs-telemetry.dll dosyasini da silebilirsiniz.
pause
