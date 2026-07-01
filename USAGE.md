# Cloudflare Scraper API — Usage Guide

A self-hosted scraping API that opens any website (passing Cloudflare where
possible), then returns the page **HTML**, a **screenshot** (as a CDN image URL),
or **both**. Optionally posts the result to a **webhook**.

- **Base URL:** `https://local-kuki-scrapper.corenexis.com`
- **Local URL (on the host PC):** `http://localhost:8723`
- **Engine:** SeleniumBase UC mode (stealth Chrome)
- **Runs:** one job at a time (the visible captcha phase uses the real mouse)

---

## Authentication

Every request (except the health check) needs your key in a header:

```
X-API-Key: YOUR_API_KEY
```

The same key is set in the server's `.env` file as `API_KEY`. A wrong/missing key
returns `401`.

---

## Endpoints

| Method | Path          | Returns                                |
|--------|---------------|----------------------------------------|
| GET    | `/`           | Health check (no key needed)           |
| POST   | `/extract`    | Full page **HTML**                     |
| POST   | `/screenshot` | **Image URL** (uploaded to Corenexis CDN) |
| POST   | `/scrape`     | **HTML + Image URL** together          |

All three POST endpoints accept the **same JSON body** below.

---

## Request parameters

| Field                   | Type    | Default | Description |
|-------------------------|---------|---------|-------------|
| `url`                   | string  | —       | **Required.** Target page to open. |
| `wait_seconds`          | int     | `5`     | Extra wait AFTER load. Use `120` for a 2-minute wait. |
| `wait_for_selector`     | string  | `""`    | Optional CSS selector to wait for before continuing (e.g. `.price`). |
| `manual_captcha_solver` | bool    | `false` | `false` = always headless, never opens a window. `true` = opens a visible browser **only** if a Cloudflare challenge is detected, to click it. |
| `full_page`             | bool    | `false` | Screenshot endpoints only. `true` captures the entire scrollable page. |
| `reconnect_time`        | int     | `4`     | UC mode reconnect timing during load. Increase for slow sites. |
| `webhook_url`           | string  | `""`    | If set, the full JSON result is POSTed to this URL after the job finishes. |

---

## How `manual_captcha_solver` works

This controls whether a browser window is ever allowed to appear.

- **`false` (default)** — The job runs fully headless in the background. **No window
  ever opens.** Best for sites with no captcha, or where the stealth pass alone is
  enough. If a site shows a hard interactive captcha, it can't be solved in this mode
  and the response comes back with `"blocked": true`.

- **`true`** — The job still tries headless first (silent). **Only if** a real
  Cloudflare challenge is detected, it relaunches in a **visible** window and clicks
  the checkbox, then continues. The window appears only when genuinely needed.

> The host PC must be **logged in with the screen unlocked** for the `true` path to
> click the captcha (it controls the real mouse).

---

## Responses

### `/extract`
```json
{
  "success": true,
  "blocked": false,
  "requested_url": "https://example.com",
  "final_url": "https://example.com/",
  "title": "Example Domain",
  "html": "<!doctype html>....</html>"
}
```

### `/screenshot`
```json
{
  "success": true,
  "blocked": false,
  "requested_url": "https://example.com",
  "final_url": "https://example.com/",
  "title": "Example Domain",
  "image_url": "https://cdn.corenexis.com/i/abc123.webp"
}
```
The image is stored on the Corenexis CDN for **24 hours** (1 day), then auto-deleted.

### `/scrape`
Same as above but includes **both** `html` and `image_url`.

### Field meanings
| Field          | Meaning |
|----------------|---------|
| `success`      | `true` if the real page loaded (not stuck on a challenge). |
| `blocked`      | `true` if a Cloudflare challenge was detected and not cleared. |
| `final_url`    | Where the browser ended up (after any redirects). |
| `title`        | Page `<title>`. |
| `html`         | Full page source (extract/scrape only). |
| `image_url`    | Public CDN link to the screenshot (screenshot/scrape only). |

---

## Webhook behaviour

If `webhook_url` is provided, the **same JSON result** is POSTed to that URL once the
job is done (best-effort, in the background). The original caller still gets the
response too. Useful for long jobs in n8n: fire the request, let the result land on
an n8n Webhook node.

---

## Errors

| HTTP | Meaning |
|------|---------|
| 401  | Invalid or missing `X-API-Key`. |
| 500  | Server `API_KEY` not configured in `.env`. |
| 502  | Screenshot uploaded but the CDN rejected it (check CDN key/quota). |
| 500  | Browser/scrape failed (bad URL, site error, timeout). |

---

## Using it in n8n

1. Add an **HTTP Request** node.
2. Click **Import cURL** (top-right of the node).
3. Paste any cURL from the examples (see below) and **Import** — method, URL,
   headers, and body auto-fill.
4. Replace `YOUR_API_KEY` with your key.

### cURL examples (n8n-import friendly)

Health:
```
curl --location 'https://local-kuki-scrapper.corenexis.com/'
```

Extract HTML:
```
curl --location 'https://local-kuki-scrapper.corenexis.com/extract' \
--header 'X-API-Key: YOUR_API_KEY' \
--header 'Content-Type: application/json' \
--data '{"url":"https://example.com","wait_seconds":5}'
```

Screenshot (full page):
```
curl --location 'https://local-kuki-scrapper.corenexis.com/screenshot' \
--header 'X-API-Key: YOUR_API_KEY' \
--header 'Content-Type: application/json' \
--data '{"url":"https://example.com","full_page":true,"wait_seconds":5}'
```

Scrape with captcha solver + webhook:
```
curl --location 'https://local-kuki-scrapper.corenexis.com/scrape' \
--header 'X-API-Key: YOUR_API_KEY' \
--header 'Content-Type: application/json' \
--data '{"url":"https://nowsecure.nl","manual_captcha_solver":true,"wait_seconds":8,"webhook_url":"https://your-n8n/webhook/abc"}'
```

---

## Limits & notes

- **One job at a time.** Extra requests queue and wait (UC mode owns the mouse).
- **Captcha solving needs an unlocked, logged-in desktop.** Don't lock the screen.
- **CDN images expire in 24h.** Save the image elsewhere if you need it longer.
- For very heavy/anti-bot sites, even UC mode can fail — those return `blocked:true`.
