@echo off
REM Genera dist\AutoFormPSV\AutoFormPSV.exe
REM Requiere: pip install pyinstaller  y  python -m playwright install chromium
python -m PyInstaller --noconfirm --windowed --name AutoFormPSV ^
  --collect-all playwright ^
  run_app.py
xcopy /E /I /Y config dist\AutoFormPSV\config
xcopy /E /I /Y data\form_cache dist\AutoFormPSV\data\form_cache
xcopy /E /I /Y output\form_schema.json dist\AutoFormPSV\output\
echo Listo: dist\AutoFormPSV\AutoFormPSV.exe
