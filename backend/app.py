"""HTTP API exposing the aSc timetable parser to the Node/Express server.

This service is called server-to-server by the CMS backend (see
server/src/services/timetablePdfParser.service.js) — never directly from the
browser — so no CORS middleware is needed here. It's deployed on Render with
a public URL, though, so every request other than /api/health must carry the
shared secret in PARSER_API_KEY — otherwise anyone on the internet could
upload PDFs and burn compute on someone else's dime.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

from parser import AscTimetableParser
from utils.logger import configure_logging

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
PDF_SIGNATURE = b"%PDF-"

# Left unset only for local dev (127.0.0.1, never reachable from outside the
# host) — set on Render so the public URL isn't wide open.
PARSER_API_KEY = os.environ.get("PARSER_API_KEY")

app = FastAPI(title="aSc Timetable Extractor API", version="1.0.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/timetable/extract")
async def extract_timetable(file: UploadFile = File(...), x_api_key: str | None = Header(default=None)) -> dict[str, object]:
    """Save an uploaded PDF temporarily and pass it to the existing parser."""
    if PARSER_API_KEY and x_api_key != PARSER_API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")

    filename = Path(file.filename or "timetable.pdf").name
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 25 MB upload limit.")
    if not payload.startswith(PDF_SIGNATURE):
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid PDF.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="asc-upload-", suffix=".pdf", delete=False) as stream:
            stream.write(payload)
            temporary_path = Path(stream.name)
        parser = AscTimetableParser(configure_logging())
        result = await asyncio.to_thread(parser.parse, temporary_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        configure_logging().exception("Extraction failed for %s", filename)
        raise HTTPException(status_code=500, detail="Timetable extraction failed.") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    if not result.slots:
        raise HTTPException(status_code=422, detail="No timetable slots were detected in this PDF.")

    data = result.to_dict()
    return {
        "success": True,
        "sourceFile": filename,
        "pageCount": result.page_count,
        "teachers": result.teachers,
        "slots": data["slots"],
        "warnings": result.warnings,
    }
