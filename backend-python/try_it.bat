@echo off
cd /d "%~dp0"

echo Setting up the quick test. First run installs libraries and may take a few minutes...
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
python scripts\ingest_knowledge.py
python try_it.py

pause
