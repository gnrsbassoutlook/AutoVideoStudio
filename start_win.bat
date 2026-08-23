@echo off
cd /d "%~dp0"
echo Starting AutoVideoStudio WebUI...
pip install -r requirements.txt -q
python app.py
pause