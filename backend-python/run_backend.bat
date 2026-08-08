@echo off
cd /d "%~dp0"

echo Setting up and starting the Ayurveda/Yoga backend. First run may take a few minutes...
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\ingest_knowledge.py
echo Starting backend on http://localhost:4000  - press Ctrl+C to stop
python server.py

pause
