"""
Cloudflare-bypass Scraper API  (SeleniumBase UC mode + FastAPI)
==============================================================
Endpoints
  GET  /            -> health check
  POST /extract     -> returns the full page HTML (text)
  POST /screenshot  -> screenshot -> uploads to Corenexis CDN -> returns image_url
  POST /scrape      -> both HTML and screenshot together

Smart browser behaviour (the key part)
  Phase 1: ALWAYS runs headless first (no window ever appears, pure backend).
  Phase 2: ONLY if a Cloudflare challenge is detected AND manual_captcha_solver
           is true, it relaunches in a VISIBLE window to physically click the
           captcha, then continues.
  => manual_captcha_solver=false  -> never opens a window (backend only)
     manual_captcha_solver=true   -> window appears only when a captcha shows up

Auth
  ONE key for everything, read from .env as API_KEY.
  - Clients send it in the  X-API-Key  header to use THIS api.
  - The SAME key is used by us when we call the Corenexis CDN.

Webhook
  If webhook_url is provided, the full result is POSTed (JSON) to that URL
  after the job finishes (in the background).
"""

import os
import io
import base64
import threading

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
from seleniumbase import SB

# ---- Config -----------------------------------------------------------------
load_dotenv()
API_KEY = os.environ.get("API_KEY")

CDN_ENDPOINT = "https://api.corenexis.com/image-cdn/v3"
CDN_DURATION_HOURS = 24          # 1 day

# High-precision markers that appear ONLY on a real Cloudflare challenge /
# interstitial page -- NOT on normal pages that merely embed a Turnstile widget
# (e.g. a contact form). This avoids false "blocked" alarms.
BLOCK_MARKERS = [
    "_cf_chl_opt",                              # challenge config object (very specific)
    "cf-challenge-running",
    "cf-browser-verification",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
]

# Titles Cloudflare shows on its interstitial page.
BLOCK_TITLES = [
    "just a moment",
    "attention required",
]

app = FastAPI(title="Cloudflare Scraper API", version="3.0")

# UC mode can control the REAL mouse (visible phase), so one job at a time.
browser_lock = threading.Lock()


# ---- Request body (shared by all endpoints) ---------------------------------
class JobRequest(BaseModel):
    url: str
    wait_seconds: int = 5            # extra wait AFTER load (e.g. 120 for 2 min)
    wait_for_selector: str = ""      # optional: wait until this CSS selector appears
    manual_captcha_solver: bool = False  # allow visible window to solve a captcha
    full_page: bool = False          # full-page screenshot (else viewport)
    reconnect_time: int = 4          # UC reconnect timing during load
    webhook_url: str = ""            # if set, result is POSTed here when done


# ---- Helpers ----------------------------------------------------------------
def _check_key(key):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server API_KEY not set in .env")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _looks_blocked(title: str, html: str) -> bool:
    # A real Cloudflare block has a tell-tale TITLE ("Just a moment...") or a
    # challenge-only marker in the HTML. Normal pages that just use a Turnstile
    # widget will NOT match these, so we don't false-alarm.
    t = title.lower().strip()
    if any(bt in t for bt in BLOCK_TITLES):
        return True
    h = html.lower()
    return any(m in h for m in BLOCK_MARKERS)


def _take_png(sb, full_page: bool) -> bytes:
    if full_page:
        try:
            data = sb.driver.execute_cdp_cmd(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True},
            )
            return base64.b64decode(data["data"])
        except Exception:
            pass
    return base64.b64decode(sb.driver.get_screenshot_as_base64())


def _upload_to_cdn(png_bytes: bytes) -> str:
    resp = requests.post(
        CDN_ENDPOINT,
        headers={"X-API-Key": API_KEY},
        files={"image": ("screenshot.png", io.BytesIO(png_bytes), "image/png")},
        data={"duration": str(CDN_DURATION_HOURS)},
        timeout=60,
    )
    try:
        body = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"CDN bad response: {resp.text[:300]}")
    if resp.status_code == 200 and body.get("success"):
        return body["data"]["url"]
    raise HTTPException(status_code=502, detail=f"CDN upload failed: {body}")


def _attempt(req: JobRequest, headless: bool, allow_click: bool,
             want_html: bool, want_shot: bool) -> dict:
    """One full browser run. Returns title, final_url, blocked, and the raw
    html / png bytes if requested."""
    with SB(uc=True, headless=headless, locale="en", ad_block=True) as sb:
        sb.uc_open_with_reconnect(req.url, reconnect_time=req.reconnect_time)

        # Only attempt the GUI captcha click in the visible phase.
        if allow_click:
            try:
                sb.uc_gui_click_captcha()
            except Exception:
                pass

        if req.wait_for_selector:
            try:
                sb.wait_for_element(req.wait_for_selector,
                                    timeout=max(req.wait_seconds, 10))
            except Exception:
                pass

        if req.wait_seconds > 0:
            sb.sleep(req.wait_seconds)

        title = sb.get_title()
        final_url = sb.get_current_url()
        html = sb.get_page_source()
        blocked = _looks_blocked(title, html)

        return {
            "title": title,
            "final_url": final_url,
            "blocked": blocked,
            "html": html if want_html else None,
            "png": _take_png(sb, req.full_page) if want_shot else None,
        }


def _run(req: JobRequest, want_html: bool, want_shot: bool) -> dict:
    # Phase 1: silent headless attempt (no window).
    res = _attempt(req, headless=True, allow_click=False,
                   want_html=want_html, want_shot=want_shot)

    # Phase 2: only if blocked AND the caller allows a visible solver.
    if res["blocked"] and req.manual_captcha_solver:
        res = _attempt(req, headless=False, allow_click=True,
                       want_html=want_html, want_shot=want_shot)

    out = {
        "success": not res["blocked"],
        "blocked": res["blocked"],
        "requested_url": req.url,
        "final_url": res["final_url"],
        "title": res["title"],
    }
    if want_html:
        out["html"] = res["html"]
    if want_shot:
        out["image_url"] = _upload_to_cdn(res["png"])
    return out


def _post_webhook(url: str, payload: dict):
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception:
        pass  # webhook is best-effort, never crash the job


def _handle(req, x_api_key, background, want_html, want_shot):
    _check_key(x_api_key)
    with browser_lock:                       # one job at a time
        result = _run(req, want_html, want_shot)
    if req.webhook_url:                      # fire-and-forget after responding
        background.add_task(_post_webhook, req.webhook_url, result)
    return result


# ---- Routes -----------------------------------------------------------------
@app.get("/")
def health():
    return {"status": "alive", "service": "cloudflare-scraper-api", "version": "3.0"}


@app.post("/extract")
def extract(req: JobRequest, background: BackgroundTasks,
            x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    return _handle(req, x_api_key, background, want_html=True, want_shot=False)


@app.post("/screenshot")
def screenshot(req: JobRequest, background: BackgroundTasks,
               x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    return _handle(req, x_api_key, background, want_html=False, want_shot=True)


@app.post("/scrape")
def scrape(req: JobRequest, background: BackgroundTasks,
           x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    return _handle(req, x_api_key, background, want_html=True, want_shot=True)