#!/usr/bin/env python3
"""SoundCloud OAuth 2.1 (PKCE) and upload helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

AUTH_BASE = "https://secure.soundcloud.com"
API_BASE = "https://api.soundcloud.com"


class SoundCloudError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def generate_pkce() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTH_BASE}/authorize?{query}"


def _http_client(**kwargs: Any) -> httpx.Client:
    # Ignore shell HTTP(S)_PROXY settings so local Cursor/sandbox proxies
    # do not break SoundCloud OAuth or uploads.
    return httpx.Client(trust_env=False, **kwargs)


def _token_request(data: Dict[str, str]) -> Dict[str, Any]:
    try:
        with _http_client(timeout=30.0) as client:
            response = client.post(
                f"{AUTH_BASE}/oauth/token",
                headers={
                    "accept": "application/json; charset=utf-8",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=data,
            )
    except httpx.HTTPError as e:
        raise SoundCloudError(f"SoundCloud token request network error: {e}") from e
    if response.status_code >= 400:
        raise SoundCloudError(
            f"SoundCloud token request failed ({response.status_code}): {response.text}",
            status=response.status_code,
            body=response.text,
        )
    payload = response.json()
    payload["obtained_at"] = int(time.time())
    return payload


def exchange_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> Dict[str, Any]:
    return _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "code": code,
        }
    )


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    return _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )


def token_expired(token: Dict[str, Any], skew_seconds: int = 60) -> bool:
    obtained = int(token.get("obtained_at") or 0)
    expires_in = int(token.get("expires_in") or 3600)
    return time.time() >= obtained + expires_in - skew_seconds


def _auth_header(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"OAuth {access_token}",
        "accept": "application/json; charset=utf-8",
    }


def _form_body(fields: List[Tuple[str, str]]) -> Tuple[Dict[str, str], bytes]:
    """Build urlencoded body.

    httpx 0.28 treats list-of-tuples passed to data= as a raw byte iterator,
    which raises: TypeError: expected a bytes-like object, tuple found.
    Always encode ourselves for repeated keys.
    """
    return (
        {"Content-Type": "application/x-www-form-urlencoded"},
        urlencode(fields).encode("utf-8"),
    )


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.status_code >= 400:
        raise SoundCloudError(
            f"{action} failed ({response.status_code}): {response.text}",
            status=response.status_code,
            body=response.text,
        )


def _track_count(playlist: Optional[Dict[str, Any]]) -> int:
    if not playlist:
        return 0
    tracks = playlist.get("tracks")
    if isinstance(tracks, list) and tracks:
        return len(tracks)
    try:
        return int(playlist.get("track_count") or 0)
    except (TypeError, ValueError):
        return 0


def get_me(access_token: str) -> Dict[str, Any]:
    try:
        with _http_client(timeout=30.0) as client:
            response = client.get(f"{API_BASE}/me", headers=_auth_header(access_token))
    except httpx.HTTPError as e:
        raise SoundCloudError(f"Fetching SoundCloud profile network error: {e}") from e
    _raise_for_status(response, "Fetching SoundCloud profile")
    return response.json()


def upload_track(
    access_token: str,
    audio_path: Path,
    title: str,
    *,
    artwork_path: Optional[Path] = None,
    artist: Optional[str] = None,
    sharing: str = "private",
    description: str = "",
) -> Dict[str, Any]:
    headers = _auth_header(access_token)

    # Put every field into multipart `files` — never mix data= + files=.
    # File bodies are raw bytes to avoid httpx tuple/stream edge cases.
    form: Dict[str, Any] = {
        "track[title]": (None, title),
        "track[sharing]": (None, sharing),
        "track[embeddable_by]": (None, "all"),
        "track[downloadable]": (None, "false"),
        "track[asset_data]": (audio_path.name, audio_path.read_bytes(), "audio/mpeg"),
    }
    if artist:
        form["track[artist]"] = (None, artist)
    if description:
        form["track[description]"] = (None, description)
    if artwork_path and artwork_path.exists():
        form["track[artwork_data]"] = (
            artwork_path.name,
            artwork_path.read_bytes(),
            _image_mime(artwork_path),
        )

    try:
        with _http_client(timeout=None) as client:
            response = client.post(
                f"{API_BASE}/tracks",
                headers=headers,
                files=form,
            )
    except httpx.HTTPError as e:
        raise SoundCloudError(f"Uploading '{title}' network error: {e}") from e

    _raise_for_status(response, f"Uploading '{title}'")
    return response.json()


def _debug_album(message: str) -> None:
    try:
        path = Path(__file__).resolve().parent / "sessions" / "last_album_debug.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def _multipart_text_fields(fields: List[Tuple[str, str]]) -> List[Tuple[str, Tuple[None, str]]]:
    # Same shape as successful track uploads — urlencoded brackets often 500 on SoundCloud.
    return [(key, (None, value)) for key, value in fields]


def create_album(
    access_token: str,
    title: str,
    track_ids: Iterable[int],
    *,
    artwork_path: Optional[Path] = None,
    sharing: str = "private",
    description: str = "",
) -> Dict[str, Any]:
    """Create a SoundCloud album (set_type=album) containing the given tracks."""
    ids = [int(t) for t in track_ids]
    id_strs = [str(i) for i in ids]
    id_csv = ",".join(id_strs)
    headers = _auth_header(access_token)
    playlist: Optional[Dict[str, Any]] = None
    errors: List[str] = []

    try:
        debug_path = Path(__file__).resolve().parent / "sessions" / "last_album_debug.txt"
        debug_path.write_text("", encoding="utf-8")
    except OSError:
        pass

    base_fields: List[Tuple[str, str]] = [
        ("playlist[title]", title),
        ("playlist[sharing]", sharing),
        ("playlist[set_type]", "album"),
    ]
    if description:
        # Keep ASCII-ish to avoid obscure gateway failures.
        base_fields.append(("playlist[description]", description.replace("—", "-")))

    # 1) Multipart create with tracks (same encoding as working track uploads).
    for label, track_fields in (
        ("multipart-csv", ([("playlist[tracks][][id]", id_csv)] if id_csv else [])),
        (
            "multipart-repeated",
            [("playlist[tracks][][id]", track_id) for track_id in id_strs],
        ),
        ("multipart-shell", []),
    ):
        if playlist:
            break
        fields = base_fields + track_fields
        try:
            with _http_client(timeout=60.0) as client:
                response = client.post(
                    f"{API_BASE}/playlists",
                    headers=headers,
                    files=_multipart_text_fields(fields),
                )
            _debug_album(f"{label} -> {response.status_code} {response.text[:800]}")
            if response.status_code < 400:
                playlist = response.json()
            else:
                errors.append(f"{label} {response.status_code}: {response.text[:240]}")
        except httpx.HTTPError as e:
            errors.append(f"{label} network: {e}")
            _debug_album(f"{label} network: {e}")

    # 2) JSON create — track ids as strings per OpenAPI schema.
    if not playlist:
        json_payload = {
            "playlist": {
                "title": title,
                "sharing": sharing,
                "set_type": "album",
                "tracks": [{"id": track_id} for track_id in id_strs],
            }
        }
        if description:
            json_payload["playlist"]["description"] = description.replace("—", "-")
        try:
            with _http_client(timeout=60.0) as client:
                response = client.post(
                    f"{API_BASE}/playlists",
                    headers=headers,
                    json=json_payload,
                )
            _debug_album(f"json-create -> {response.status_code} {response.text[:800]}")
            if response.status_code < 400:
                playlist = response.json()
            else:
                errors.append(f"json-create {response.status_code}: {response.text[:240]}")
        except httpx.HTTPError as e:
            errors.append(f"json-create network: {e}")

    if not playlist:
        raise SoundCloudError(
            "Creating SoundCloud album failed. " + " | ".join(errors)
        )

    playlist_id = playlist.get("id")
    if not playlist_id:
        raise SoundCloudError(
            f"Creating SoundCloud album failed: missing playlist id. "
            f"Errors: {' | '.join(errors)}. Response: {playlist}"
        )

    # Fresh uploads can lag before they attach — retry a few times.
    for attempt in range(5):
        count = _track_count(playlist)
        if ids and count < len(ids):
            if attempt:
                time.sleep(1.5 * attempt)
            updated = set_playlist_tracks(access_token, int(playlist_id), ids)
            if updated:
                playlist = updated
            if _track_count(playlist) < len(ids):
                updated = set_playlist_tracks_json(access_token, int(playlist_id), ids)
                if updated:
                    playlist = updated
        fetched = get_playlist(access_token, int(playlist_id), show_tracks=True)
        if fetched:
            playlist = fetched
        if not ids or _track_count(playlist) >= len(ids):
            break

    # Artwork is optional — never fail the whole publish if this errors.
    if artwork_path and artwork_path.exists():
        try:
            updated = update_playlist_artwork(access_token, int(playlist_id), artwork_path)
            if updated:
                playlist = updated
        except Exception:
            pass

    fetched = get_playlist(access_token, int(playlist_id), show_tracks=True)
    if fetched:
        playlist = fetched

    count = _track_count(playlist)
    if ids and count < 1:
        playlist["_attach_warning"] = (
            f"Album created (id={playlist_id}) but SoundCloud reported 0 tracks attached "
            f"(expected {len(ids)}). Open the album link and check Library → Albums/Playlists."
        )
    return playlist


def set_playlist_tracks(
    access_token: str,
    playlist_id: int,
    track_ids: Iterable[int],
) -> Optional[Dict[str, Any]]:
    """Attach tracks via multipart form (csv, then repeated ids)."""
    headers = _auth_header(access_token)
    id_strs = [str(int(track_id)) for track_id in track_ids]
    attempts = [
        [("playlist[tracks][][id]", ",".join(id_strs))],
        [("playlist[tracks][][id]", track_id) for track_id in id_strs],
    ]
    for fields in attempts:
        try:
            with _http_client(timeout=60.0) as client:
                response = client.put(
                    f"{API_BASE}/playlists/{playlist_id}",
                    headers=headers,
                    files=_multipart_text_fields(fields),
                )
            _debug_album(f"attach-multipart -> {response.status_code} {response.text[:500]}")
            if response.status_code < 400:
                return response.json()
        except httpx.HTTPError as e:
            _debug_album(f"attach-multipart network: {e}")
    return None


def set_playlist_tracks_json(
    access_token: str,
    playlist_id: int,
    track_ids: Iterable[int],
) -> Optional[Dict[str, Any]]:
    headers = _auth_header(access_token)
    payload = {
        "playlist": {
            "tracks": [{"id": str(int(track_id))} for track_id in track_ids],
        }
    }
    try:
        with _http_client(timeout=60.0) as client:
            response = client.put(
                f"{API_BASE}/playlists/{playlist_id}",
                headers=headers,
                json=payload,
            )
        _debug_album(f"attach-json -> {response.status_code} {response.text[:500]}")
    except httpx.HTTPError as e:
        _debug_album(f"attach-json network: {e}")
        return None
    if response.status_code >= 400:
        return None
    return response.json()


def get_playlist(
    access_token: str,
    playlist_id: int,
    *,
    show_tracks: bool = False,
) -> Optional[Dict[str, Any]]:
    try:
        with _http_client(timeout=30.0) as client:
            response = client.get(
                f"{API_BASE}/playlists/{playlist_id}",
                headers=_auth_header(access_token),
                params={"show_tracks": "true" if show_tracks else "false"},
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    return response.json()


def update_playlist_artwork(
    access_token: str,
    playlist_id: int,
    artwork_path: Path,
) -> Optional[Dict[str, Any]]:
    if not artwork_path.exists():
        return None
    headers = _auth_header(access_token)
    form = {
        "playlist[artwork_data]": (
            artwork_path.name,
            artwork_path.read_bytes(),
            _image_mime(artwork_path),
        )
    }
    try:
        with _http_client(timeout=60.0) as client:
            response = client.put(
                f"{API_BASE}/playlists/{playlist_id}",
                headers=headers,
                files=form,
            )
    except httpx.HTTPError as e:
        raise SoundCloudError(f"Updating album artwork network error: {e}") from e
    if response.status_code >= 400:
        return None
    return response.json()


def _image_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
