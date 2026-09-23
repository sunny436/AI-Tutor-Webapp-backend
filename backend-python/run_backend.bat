@echo off
REM Start the chat API locally (Windows). Requires docker-compose.dev.yml to be up.
REM   docker compose -f ..\docker-compose.dev.yml up -d
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Create the virtualenv first:  py -3.12 -m venv .venv  ^&^&  .venv\Scripts\python -m pip install -r requirements-dev.txt
  exit /b 1
)
.venv\Scripts\python -m alembic upgrade head || exit /b 1
.venv\Scripts\python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 4000 --reload
