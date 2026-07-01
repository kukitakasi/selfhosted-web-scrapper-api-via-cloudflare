@echo off
REM ====== Cloudflare Scraper API launcher ======
REM Run automatically at logon by Task Scheduler.
REM Listens only on localhost; Cloudflare Tunnel exposes it to your subdomain.

cd /d C:\scraper-api
call venv\Scripts\activate.bat

REM Unique local port 8723 (not a common one) + single worker (UC = one job at a time)
python -m uvicorn app:app --host 127.0.0.1 --port 8723 --workers 1

REM Keep window open if it crashes, so you can read the error
pause
