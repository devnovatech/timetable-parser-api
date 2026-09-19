# Timetable PDF Parser

A small FastAPI service that extracts teacher-wise and class-wise timetable
records from digitally generated aSc Timetables PDFs, using positioned PDF
text and vector drawing geometry — no OCR, no AI/LLM calls. It's called
server-to-server by the main API (`server/src/services/timetablePdfParser.service.js`)
when an admin uses "Import PDF" on the Timetable page; it is never called
directly from the browser.

## Run

Python 3.11+ required.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --reload --port 8001
```

Set `TIMETABLE_PARSER_URL=http://127.0.0.1:8001` in `server/.env` (this is
already the default, so it only needs setting if you run this service on a
different host/port). `PARSER_API_KEY` can stay unset for local dev.

## Deploying (Render)

Hostinger's "Web Apps" (used for the main Node app) is Node.js-only, so this
service needs somewhere with a real Python runtime — Render's free "Web
Service" tier works well since this is called occasionally, not continuously.

1. Render dashboard → **New +** → **Web Service** → connect this repo.
2. **Runtime**: Python 3 (Render reads `runtime.txt` for the exact version)
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`
5. **Environment variable**: `PARSER_API_KEY` = a long random string (e.g.
   `openssl rand -hex 32`) — this is now a public URL, so this key is what
   stops random internet traffic from hitting it. Without it, anyone with the
   URL could upload PDFs and burn your Render compute.
6. Deploy, then copy the assigned `https://<your-service>.onrender.com` URL.
7. On the Node server (Hostinger env vars), set:
   ```
   TIMETABLE_PARSER_URL=https://<your-service>.onrender.com
   TIMETABLE_PARSER_API_KEY=<the same PARSER_API_KEY value>
   ```

**Free tier note:** the service sleeps after ~15 min idle; the first PDF
import after a lull takes ~30–50s while it wakes up (the request just waits
longer — no code change needed to handle this). Fine for an admin action
used occasionally; upgrade to a paid instance if that delay is a problem.

## API

```text
GET  /api/health
POST /api/timetable/extract   (multipart field "file", a PDF; header
                                X-Api-Key required if PARSER_API_KEY is set)
```

Uploads are limited to 25 MB and deleted from temporary storage immediately
after parsing.

## Parser boundaries

The parser is deliberately conservative. Missing teacher, class, room, grid,
or time information produces warnings and lowers each slot's confidence
rather than inventing a value. A malformed page is logged and skipped
without aborting the rest of the document. Scanned/image-only PDFs are out
of scope — they have no positioned text or vector geometry to read.
