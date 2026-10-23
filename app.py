#!/usr/bin/env python3
"""SplitTracks web app: split a kirtan recording and post an unlisted SoundCloud album."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import soundcloud_client as sc
from splitter import (
    SplitError,
    SUPPORTED_AUDIO_EXTENSIONS,
    Segment,
    check_tool_available,
    export_segment,
    parse_time_to_seconds,
    parse_timestamp_text,
    probe_duration_seconds,
    sanitize_label,
)

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

STATIC_DIR = ROOT / "static"
SESSIONS_DIR = ROOT / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ENV_KEYS = ("SOUNDCLOUD_CLIENT_ID", "SOUNDCLOUD_CLIENT_SECRET", "SOUNDCLOUD_REDIRECT_URI")


def _secret_key() -> str:
    secret_path = ROOT / ".secret"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    secret_path.write_text(value + "\n", encoding="utf-8")
    return value


app = FastAPI(title="SplitTracks")
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key(),
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=False,
)


def session_dir(request: Request) -> Path:
    sid = request.session.get("sid")
    if not sid:
        sid = uuid4().hex
        request.session["sid"] = sid
    path = SESSIONS_DIR / sid
    (path / "thumbs").mkdir(parents=True, exist_ok=True)
    (path / "tracks").mkdir(parents=True, exist_ok=True)
    return path


def env_get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def client_config(request: Request) -> Dict[str, str]:
    stored = request.session.get("sc_keys") or {}
    client_id = stored.get("client_id") or env_get("SOUNDCLOUD_CLIENT_ID")
    client_secret = stored.get("client_secret") or env_get("SOUNDCLOUD_CLIENT_SECRET")
    redirect_uri = (
        stored.get("redirect_uri")
        or env_get("SOUNDCLOUD_REDIRECT_URI")
        or str(request.base_url).rstrip("/") + "/api/auth/callback"
    )
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def upsert_env_values(values: Dict[str, str]) -> None:
    env_path = ROOT / ".env"
    existing: Dict[str, str] = {}
    lines: List[str] = []
    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                lines.append(line)
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key in values:
                existing[key] = val
                continue
            lines.append(line)
            existing[key] = val

    for key, val in values.items():
        lines.append(f"{key}={val}")
        os.environ[key] = val

    text = "\n".join(lines).rstrip() + "\n"
    env_path.write_text(text, encoding="utf-8")


def find_named(directory: Path, stem: str) -> Optional[Path]:
    if not directory.exists():
        return None
    for path in directory.iterdir():
        if path.is_file() and path.stem == stem:
            return path
    return None


def audio_path(request: Request) -> Optional[Path]:
    return find_named(session_dir(request), "audio")


def album_art_path(request: Request) -> Optional[Path]:
    return find_named(session_dir(request), "album")


def thumb_path(request: Request, keertani_id: str) -> Optional[Path]:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", keertani_id)
    return find_named(session_dir(request) / "thumbs", safe)


def save_upload(upload: UploadFile, dest_without_suffix: Path, allowed: set[str]) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(allowed))}",
        )
    dest_without_suffix.parent.mkdir(parents=True, exist_ok=True)
    for old in dest_without_suffix.parent.glob(dest_without_suffix.name + ".*"):
        if old.stem == dest_without_suffix.name:
            old.unlink(missing_ok=True)
    dest = dest_without_suffix.with_suffix(suffix)
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return dest


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def public_user(me: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": me.get("id"),
        "username": me.get("username") or me.get("permalink") or "",
        "full_name": me.get("full_name") or "",
        "avatar_url": me.get("avatar_url") or "",
    }


def ensure_access_token(request: Request) -> str:
    cfg = client_config(request)
    token = request.session.get("sc_token")
    if not token:
        raise HTTPException(status_code=401, detail="Sign in with SoundCloud to continue.")
    if sc.token_expired(token):
        refresh = token.get("refresh_token")
        if not refresh:
            request.session.pop("sc_token", None)
            raise HTTPException(status_code=401, detail="SoundCloud session expired. Sign in again.")
        try:
            token = sc.refresh_access_token(cfg["client_id"], cfg["client_secret"], refresh)
        except sc.SoundCloudError as e:
            request.session.pop("sc_token", None)
            raise HTTPException(status_code=401, detail=str(e)) from e
        request.session["sc_token"] = token
    return token["access_token"]


def build_track_title(item: Dict[str, Any]) -> str:
    honorific = (item.get("honorific") or "Bhai").strip()
    name = (item.get("name") or "").strip()
    title = (item.get("title") or ("Kaur Jee" if honorific == "Bibi" else "Singh Jee")).strip()
    origin = (item.get("origin") or "").strip()
    program = (item.get("program") or "").strip()
    parts = [part for part in (honorific, name, title) if part]
    line = " ".join(parts)
    if origin:
        line = f"{line} {origin}".strip()
    if program:
        line = f"{line} - {program}".strip(" -")
    return sanitize_label(line)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/session")
async def get_session_state(request: Request) -> Dict[str, Any]:
    audio = audio_path(request)
    art = album_art_path(request)
    duration = request.session.get("audio_duration")
    cfg = client_config(request)
    token = request.session.get("sc_token")
    thumbs_dir = session_dir(request) / "thumbs"
    thumbs = [p.stem for p in thumbs_dir.glob("*") if p.is_file()] if thumbs_dir.exists() else []
    return {
        "audio": (
            {
                "filename": request.session.get("audio_filename") or audio.name,
                "duration": duration,
                "duration_label": format_duration(duration) if duration else None,
            }
            if audio
            else None
        ),
        "album_art": bool(art),
        "thumbnails": thumbs,
        "has_keys": bool(cfg["client_id"] and cfg["client_secret"]),
        "redirect_uri": cfg["redirect_uri"],
        "authenticated": bool(token),
        "user": request.session.get("sc_user"),
        "draft": request.session.get("draft"),
    }


@app.post("/api/audio")
async def upload_audio(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        check_tool_available("ffmpeg")
        check_tool_available("ffprobe")
    except SplitError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    dest = save_upload(file, session_dir(request) / "audio", SUPPORTED_AUDIO_EXTENSIONS)
    try:
        duration = probe_duration_seconds(dest)
    except SplitError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    request.session["audio_filename"] = file.filename or dest.name
    request.session["audio_duration"] = duration
    return {
        "filename": request.session["audio_filename"],
        "duration": duration,
        "duration_label": format_duration(duration),
    }


@app.delete("/api/audio")
async def delete_audio(request: Request) -> Dict[str, Any]:
    path = audio_path(request)
    if path:
        path.unlink(missing_ok=True)
    request.session.pop("audio_filename", None)
    request.session.pop("audio_duration", None)
    return {"ok": True}


@app.post("/api/timestamps")
async def parse_timestamps(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        return {"rows": []}
    duration = request.session.get("audio_duration")
    try:
        rows = parse_timestamp_text(text, duration)
    except SplitError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "rows": [
            {"name": row.name, "start": row.start_text, "end": row.end_text}
            for row in rows
        ],
    }


@app.delete("/api/thumbnails")
async def delete_all_thumbnails(request: Request) -> Dict[str, Any]:
    thumbs = session_dir(request) / "thumbs"
    if thumbs.exists():
        shutil.rmtree(thumbs)
    thumbs.mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@app.post("/api/restart")
async def restart_session(request: Request) -> Dict[str, Any]:
    sid = request.session.get("sid")
    path = SESSIONS_DIR / sid if sid else None
    if path and path.exists():
        shutil.rmtree(path)
    request.session.pop("audio_filename", None)
    request.session.pop("audio_duration", None)
    request.session.pop("draft", None)
    if sid:
        session_dir(request)
    return {"ok": True}


@app.post("/api/album-art")
async def upload_album_art(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    dest = save_upload(file, session_dir(request) / "album", IMAGE_EXTENSIONS)
    return {"ok": True, "filename": dest.name}


@app.delete("/api/album-art")
async def delete_album_art(request: Request) -> Dict[str, Any]:
    art = album_art_path(request)
    if art:
        art.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/thumbnail/{keertani_id}")
async def upload_thumbnail(
    keertani_id: str, request: Request, file: UploadFile = File(...)
) -> Dict[str, Any]:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", keertani_id)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid keertani id.")
    dest = save_upload(file, session_dir(request) / "thumbs" / safe, IMAGE_EXTENSIONS)
    return {"ok": True, "id": safe, "filename": dest.name}


@app.delete("/api/thumbnail/{keertani_id}")
async def delete_thumbnail(keertani_id: str, request: Request) -> Dict[str, Any]:
    path = thumb_path(request, keertani_id)
    if path:
        path.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/files/album-art")
async def serve_album_art(request: Request) -> FileResponse:
    art = album_art_path(request)
    if not art:
        raise HTTPException(status_code=404, detail="No album art.")
    return FileResponse(art)


@app.get("/api/files/thumb/{keertani_id}")
async def serve_thumb(keertani_id: str, request: Request) -> FileResponse:
    path = thumb_path(request, keertani_id)
    if not path:
        raise HTTPException(status_code=404, detail="No thumbnail.")
    return FileResponse(path)


@app.put("/api/draft")
async def save_draft(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    request.session["draft"] = payload
    return {"ok": True}


@app.post("/api/keys")
async def save_keys(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    client_id = (payload.get("client_id") or "").strip()
    client_secret = (payload.get("client_secret") or "").strip()
    redirect_uri = (payload.get("redirect_uri") or "").strip() or (
        str(request.base_url).rstrip("/") + "/api/auth/callback"
    )
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Client ID and secret are required.")
    request.session["sc_keys"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    upsert_env_values(
        {
            "SOUNDCLOUD_CLIENT_ID": client_id,
            "SOUNDCLOUD_CLIENT_SECRET": client_secret,
            "SOUNDCLOUD_REDIRECT_URI": redirect_uri,
        }
    )
    return {"ok": True, "redirect_uri": redirect_uri}


@app.get("/api/auth/login")
async def auth_login(request: Request) -> RedirectResponse:
    cfg = client_config(request)
    if not cfg["client_id"] or not cfg["client_secret"]:
        return RedirectResponse("/?need_keys=1", status_code=302)
    verifier, challenge = sc.generate_pkce()
    state = sc.generate_state()
    request.session["pkce_verifier"] = verifier
    request.session["oauth_state"] = state
    url = sc.authorize_url(cfg["client_id"], cfg["redirect_uri"], challenge, state)
    return RedirectResponse(url, status_code=302)


@app.get("/api/auth/callback")
async def auth_callback(
    request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None
) -> RedirectResponse:
    if error:
        return RedirectResponse(f"/?auth_error={error}", status_code=302)
    if not code or state != request.session.get("oauth_state"):
        return RedirectResponse("/?auth_error=invalid_state", status_code=302)
    cfg = client_config(request)
    verifier = request.session.get("pkce_verifier")
    if not verifier:
        return RedirectResponse("/?auth_error=missing_verifier", status_code=302)
    try:
        token = sc.exchange_code(
            cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"], code, verifier
        )
        me = sc.get_me(token["access_token"])
    except sc.SoundCloudError as e:
        return RedirectResponse(f"/?auth_error={e.status or 'token'}", status_code=302)

    request.session["sc_token"] = token
    request.session["sc_user"] = public_user(me)
    request.session.pop("pkce_verifier", None)
    request.session.pop("oauth_state", None)
    return RedirectResponse("/?connected=1", status_code=302)


@app.post("/api/auth/logout")
async def auth_logout(request: Request) -> Dict[str, Any]:
    request.session.pop("sc_token", None)
    request.session.pop("sc_user", None)
    return {"ok": True}


@app.post("/api/publish")
async def publish(request: Request) -> StreamingResponse:
    payload = await request.json()
    request.session["draft"] = payload

    audio = audio_path(request)
    if not audio:
        raise HTTPException(status_code=400, detail="Upload an audio file first.")

    album_name = (payload.get("album_name") or payload.get("program") or "").strip()
    if not album_name:
        raise HTTPException(status_code=400, detail="Give this program a name.")

    keertanis = payload.get("keertanis") or []
    if not keertanis:
        raise HTTPException(status_code=400, detail="Add at least one keertani.")

    duration = request.session.get("audio_duration")
    if duration is None:
        duration = probe_duration_seconds(audio)

    cfg = client_config(request)
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=400,
            detail="Add your SoundCloud app Client ID and Secret before posting.",
        )

    try:
        access_token = ensure_access_token(request)
    except HTTPException as e:
        if e.status_code == 401:
            return JSONResponse({"auth_required": True, "login": "/api/auth/login"}, status_code=401)
        raise

    prepared: List[Dict[str, Any]] = []
    for index, item in enumerate(keertanis, start=1):
        title = build_track_title(item)
        if not (item.get("name") or "").strip():
            raise HTTPException(status_code=400, detail=f"Keertani {index} is missing a name.")
        try:
            start = parse_time_to_seconds(str(item.get("start") or ""), duration)
            end = parse_time_to_seconds(str(item.get("end") or ""), duration)
        except SplitError as e:
            raise HTTPException(status_code=400, detail=f"Keertani {index}: {e}") from e
        if end <= start:
            raise HTTPException(
                status_code=400,
                detail=f"Keertani {index}: end timestamp must be after start.",
            )
        prepared.append(
            {
                "index": index,
                "id": str(item.get("id") or index),
                "title": title,
                "artist": " ".join(
                    part
                    for part in (
                        (item.get("honorific") or "").strip(),
                        (item.get("name") or "").strip(),
                        (item.get("title") or "").strip(),
                    )
                    if part
                ),
                "segment": Segment(label=title, start_seconds=start, end_seconds=end),
            }
        )

    work_dir = session_dir(request)
    tracks_dir = work_dir / "tracks"
    if tracks_dir.exists():
        shutil.rmtree(tracks_dir)
    tracks_dir.mkdir(parents=True, exist_ok=True)
    fallback_art = album_art_path(request)
    total = len(prepared)

    def sse(event: str, data: Dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def generate():
        try:
            check_tool_available("ffmpeg")
            check_tool_available("ffprobe")
            token = access_token
            uploaded_ids: List[int] = []
            uploaded_tracks: List[Dict[str, Any]] = []
            width = max(2, len(str(total)))

            for item in prepared:
                index = item["index"]
                title = item["title"]
                yield sse(
                    "progress",
                    {
                        "stage": "split",
                        "index": index,
                        "total": total,
                        "title": title,
                        "message": f"Splitting {index}/{total}: {title}",
                    },
                )
                outfile = tracks_dir / f"{str(index).zfill(width)} - {title}.mp3"
                export_segment(audio, outfile, item["segment"])

                yield sse(
                    "progress",
                    {
                        "stage": "upload",
                        "index": index,
                        "total": total,
                        "title": title,
                        "message": f"Uploading {index}/{total}: {title}",
                    },
                )
                art = thumb_path(request, item["id"]) or fallback_art
                track = sc.upload_track(
                    token,
                    outfile,
                    title,
                    artwork_path=art,
                    artist=item["artist"],
                    sharing="private",
                    description=album_name,
                )
                track_id = int(track["id"])
                uploaded_ids.append(track_id)
                permalink = track.get("permalink_url") or track.get("secret_uri") or ""
                if track.get("secret_token") and permalink and "secret_token" not in permalink:
                    permalink = f"{permalink}/{track['secret_token']}"
                uploaded_tracks.append(
                    {
                        "id": track_id,
                        "title": track.get("title") or title,
                        "permalink_url": permalink,
                    }
                )

            yield sse(
                "progress",
                {
                    "stage": "album",
                    "index": total,
                    "total": total,
                    "title": album_name,
                    "message": f"Creating unlisted album: {album_name}",
                },
            )
            playlist = sc.create_album(
                token,
                album_name,
                uploaded_ids,
                artwork_path=fallback_art,
                sharing="private",
                description=f"{total} keertanis — posted with SplitTracks",
            )
            playlist_url = playlist.get("permalink_url") or ""
            if playlist.get("secret_token") and playlist_url and "secret_token" not in playlist_url:
                playlist_url = f"{playlist_url}/{playlist['secret_token']}"

            yield sse(
                "done",
                {
                    "album": album_name,
                    "playlist_url": playlist_url,
                    "tracks": uploaded_tracks,
                },
            )
        except (SplitError, sc.SoundCloudError, OSError) as e:
            yield sse("error", {"message": str(e)})
        except Exception as e:
            yield sse("error", {"message": f"Unexpected error: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    host = env_get("HOST", "127.0.0.1")
    port = int(env_get("PORT", "8000") or 8000)
    uvicorn.run("app:app", host=host, port=port, reload=True)
