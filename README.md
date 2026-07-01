# Cloudflare Scraper API — Full Setup Guide (Windows, via CMD)

This guide documents the exact steps used to build the API from scratch on Windows:
local install → run → auto-start on boot → public domain via Cloudflare Tunnel.

**Final result:** a public API at `https://local-kuki-scrapper.corenexis.com` that
runs on your own PC, starts automatically, and is reachable from anywhere.

---

## Architecture (what runs where)

```
Internet  ->  Cloudflare  ->  Cloudflare Tunnel (Windows service, auto-start)
                                   |
                                   v
                       Scraper API  (uvicorn on localhost:8723)
                                   |
                                   v
                  SeleniumBase UC (stealth Chrome)  ->  screenshot/html
                                   |
                                   v
                  Corenexis CDN  (screenshot -> image URL, 24h)
```

Two things auto-start:
- **Cloudflare Tunnel** = a Windows **service** (runs at boot, no login needed).
- **The API** = a Task Scheduler task at **logon** (needs a desktop so the visible
  captcha phase can click the mouse).

---

## 0. Prerequisites

- Windows 10/11
- Google Chrome installed
- Python 3.10+ from **python.org** (NOT the Microsoft Store version)
  - During install, tick **"Add python.exe to PATH"**
- The domain `corenexis.com` managed on **Cloudflare** (DNS on Cloudflare)
- A Corenexis Image CDN API key

Verify Python (open a NEW cmd after installing):
```cmd
python --version
```

---

## 1. Create the project folder

```cmd
mkdir C:\scraper-api
cd C:\scraper-api
```

---

## 2. Virtual environment + packages

```cmd
cd C:\scraper-api
python -m venv venv
call venv\Scripts\activate.bat
pip install seleniumbase fastapi "uvicorn[standard]" pydantic python-dotenv requests
```
Success when the prompt shows `(venv)` and pip ends with `Successfully installed ...`.

---

## 3. Create the .env file (single API key)

One key is used for BOTH: unlocking this API and calling the Corenexis CDN.

```cmd
cd C:\scraper-api
(echo API_KEY=your-corenexis-key-here)> .env
type .env
```
`type .env` should print exactly one line: `API_KEY=...` (no spaces, no `.txt`).

---

## 4. Add app.py

Place `app.py` (the application code) into `C:\scraper-api\`.

Verify everything is present:
```cmd
cd C:\scraper-api
dir
```
You should see: `app.py`, `.env`, `venv\`, `start_api.bat`.

---

## 5. Run + test locally (port 8723)

```cmd
cd C:\scraper-api
call venv\Scripts\activate.bat
python -m uvicorn app:app --host 127.0.0.1 --port 8723 --workers 1
```
Look for: `Application startup complete` and `Uvicorn running on http://127.0.0.1:8723`.

In a SECOND cmd window:
```cmd
curl http://localhost:8723/
```
Expected: `{"status":"alive","service":"cloudflare-scraper-api","version":"3.0"}`

Real test (replace key):
```cmd
curl -X POST "http://localhost:8723/screenshot" -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" -d "{\"url\":\"https://example.com\",\"wait_seconds\":3}"
```
You should get back an `image_url`. Stop the server with Ctrl+C.

> Note: port **8723** is deliberately uncommon to avoid clashing with other apps.

---

## 6. Auto-login (so a desktop is ready at boot)

The visible captcha phase needs a logged-in session.

```cmd
netplwiz
```
Untick "Users must enter a user name and password..." → Apply → enter password → OK.

**Microsoft account?** That checkbox may be hidden. Simplest path: skip auto-login and
just log in manually after a reboot — the API task (next step) fires on logon. The
tunnel runs regardless because it's a service.

---

## 7. Auto-start the API at logon (Task Scheduler) — hidden window

If you point the task directly at `start_api.bat`, a black CMD window stays open
the whole time. To run it **silently in the background** (no visible window), use a
tiny VBScript launcher.

### 7a. Create the hidden launcher

Make `C:\scraper-api\run_hidden.vbs` with Notepad (works from any shell, no escaping):
```cmd
notepad C:\scraper-api\run_hidden.vbs
```
Paste exactly this one line, then save:
```
CreateObject("Wscript.Shell").Run "cmd /c C:\scraper-api\start_api.bat", 0, False
```
The `0` means "do not show a window". Verify:
```cmd
type C:\scraper-api\run_hidden.vbs
```

(PowerShell one-liner alternative:)
```powershell
Set-Content -Path "C:\scraper-api\run_hidden.vbs" -Value 'CreateObject("Wscript.Shell").Run "cmd /c C:\scraper-api\start_api.bat", 0, False'
```

### 7b. Create the task pointing at the hidden launcher

Open cmd **as Administrator**, then:
```cmd
schtasks /create /tn "ScraperAPI" /tr "wscript.exe C:\scraper-api\run_hidden.vbs" /sc onlogon /rl highest /f
```
Expected: `SUCCESS: The scheduled task "ScraperAPI" has successfully been created.`

### 7c. Test (no window should appear)

Close any visible uvicorn window first, then:
```cmd
schtasks /run /tn "ScraperAPI"
```
Wait ~4 seconds. No window should open. Confirm it is running anyway:
```cmd
curl http://localhost:8723/
tasklist | findstr python
```
`curl` returns the alive JSON and `python.exe` shows in the task list.

Manage later:
```cmd
schtasks /end /tn "ScraperAPI"        REM stop it
schtasks /run /tn "ScraperAPI"        REM start it
schtasks /delete /tn "ScraperAPI" /f  REM remove it
```

> The hidden window only hides uvicorn's own console. When a site needs the visible
> captcha solver (`manual_captcha_solver:true`), Chrome still appears so it can be
> clicked — that is expected and unaffected.

---

## 8. Cloudflare Tunnel — public domain

### 8a. Download cloudflared
```cmd
cd C:\scraper-api
curl -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
cloudflared.exe --version
```

### 8b. Create the tunnel (dashboard)
1. Go to https://one.dash.cloudflare.com/
2. **Networks → Tunnels → Create a tunnel → Cloudflared**
3. Name it `kuki-scrapper` → Save.
4. On "Install connector", choose **Windows** and copy the **token** (the long
   `eyJ...` string from the shown command).

### 8c. Install the tunnel as a Windows service (auto-start)
Admin cmd:
```cmd
cd C:\scraper-api
cloudflared.exe service install YOUR_LONG_TOKEN_HERE
sc query cloudflared
```
`sc query cloudflared` should show `STATE : 4 RUNNING`.

### 8d. Add the public hostname (dashboard)
Back in the tunnel setup → **Public Hostname → Add**:
- Subdomain: `local-kuki-scrapper`
- Domain: `corenexis.com`
- Type: `HTTP`
- URL: `localhost:8723`

Save. Cloudflare creates the DNS record automatically.

---

## 9. Verify the public API

```cmd
curl https://local-kuki-scrapper.corenexis.com/
```
Expected: the alive JSON — now served from the internet.

```cmd
curl -X POST "https://local-kuki-scrapper.corenexis.com/screenshot" -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" -d "{\"url\":\"https://example.com\",\"wait_seconds\":3}"
```

Done. After any restart: log in (or auto-login) → API task starts, tunnel service
is already up → the public URL works.

---

## Maintenance

**Update the code:** replace `C:\scraper-api\app.py`, then restart the API:
```cmd
schtasks /end /tn "ScraperAPI"
schtasks /run /tn "ScraperAPI"
```

**Change the API key:** edit `.env`, then restart the API task as above.

**Tunnel service control:**
```cmd
sc query cloudflared
sc stop cloudflared
sc start cloudflared
```

**Check what's using port 8723:**
```cmd
netstat -ano | findstr :8723
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `'python' is not recognized` | Reinstall Python from python.org with "Add to PATH"; open a NEW cmd. |
| `ERROR: Access is denied` on schtasks | Run cmd as Administrator. |
| Response has `"blocked": true` but page is fine | Detection edge case — the page loaded; check the HTML/screenshot. Hard sites need `manual_captcha_solver:true`. |
| Browser opens every time | It shouldn't with `manual_captcha_solver:false`. With `true` it opens only on a real challenge. |
| Captcha not clicked | Screen must be unlocked and logged in; don't RDP-disconnect. |
| Public URL not reachable | `sc query cloudflared` (must be RUNNING) and confirm the public hostname points to `localhost:8723`. |
| Port 8723 busy | Another process took it — change the port in `start_api.bat` and the tunnel hostname URL to match. |
| Black CMD window stays open always | Use the hidden VBS launcher (Step 7a) and point the task at `wscript.exe ...run_hidden.vbs` instead of the `.bat`. |
| `Unexpected token '^'` when creating the .vbs | You ran the CMD `echo ... ^` line inside PowerShell. Use Notepad (Step 7a) or the PowerShell `Set-Content` one-liner instead. |
| `curl: (7) Failed to connect to localhost 8723` | The API isn't running. Start it: `schtasks /run /tn "ScraperAPI"`. If it still fails, run uvicorn manually to read the error. |
| Tunnel shows "Bad gateway" | The API is down or the public hostname Type is wrong. Confirm `curl http://localhost:8723/` works, and set the hostname **Type = HTTP**, **URL = localhost:8723**. |
| n8n returns `405 Method Not Allowed` | The HTTP node is using GET. Set Method = **POST** for `/extract`, `/screenshot`, `/scrape`. |

---

## Security reminders

- Keep the API key secret. Regenerate it in the Corenexis dashboard if it leaks.
- The API listens only on `localhost` — the internet reaches it only through the
  Cloudflare Tunnel, which provides HTTPS and hides your home IP.
- Keep Windows and Chrome updated.
