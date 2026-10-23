#!/usr/bin/env python3
"""SoundCloud OAuth 2.1 (PKCE) and upload helpers."""

from __future__ import annotations

import base64
import hashlib
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


def _token_request(data: Dict[str, str]) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{AUTH_BASE}/oauth/token",
            headers={
                "accept": "application/json; charset=utf-8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
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


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.status_code >= 400:
        raise SoundCloudError(
            f"{action} failed ({response.status_code}): {response.text}",
            status=response.status_code,
            body=response.text,
        )


def get_me(access_token: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{API_BASE}/me", headers=_auth_header(access_token))
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
    # Let httpx set multipart content-type with boundary.
    headers.pop("Content-Type", None)

    data = {
        "track[title]": title,
        "track[sharing]": sharing,
        "track[embeddable_by]": "all",
        "track[downloadable]": "false",
    }
    if artist:
        data["track[artist]"] = artist
    if description:
        data["track[description]"] = description

    files: List[Tuple[str, Tuple[str, Any, str]]] = [
        (
            "track[asset_data]",
            (audio_path.name, audio_path.open("rb"), "audio/mpeg"),
        )
    ]
    if artwork_path and artwork_path.exists():
        files.append(
            (
                "track[artwork_data]",
                (artwork_path.name, artwork_path.open("rb"), _image_mime(artwork_path)),
            )
        )

    try:
        with httpx.Client(timeout=None) as client:
            response = client.post(
                f"{API_BASE}/tracks",
                headers=headers,
                data=data,
                files=files,
            )
    finally:
        for _, file_tuple in files:
            file_tuple[1].close()

    _raise_for_status(response, f"Uploading '{title}'")
    return response.json()


def create_album(
    access_token: str,
    title: str,
    track_ids: Iterable[int],
    *,
    artwork_path: Optional[Path] = None,
    sharing: str = "private",
    description: str = "",
) -> Dict[str, Any]:
    ids = [int(t) for t in track_ids]
    headers = _auth_header(access_token)

    if artwork_path and artwork_path.exists():
        data = [
            ("playlist[title]", title),
            ("playlist[sharing]", sharing),
            ("playlist[playlist_type]", "album"),
        ]
        if description:
            data.append(("playlist[description]", description))
        for track_id in ids:
            data.append(("playlist[tracks][][id]", str(track_id)))

        files = {
            "playlist[artwork_data]": (
                artwork_path.name,
                artwork_path.open("rb"),
                _image_mime(artwork_path),
            )
        }
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{API_BASE}/playlists",
                    headers=headers,
                    data=data,
                    files=files,
                )
        finally:
            files["playlist[artwork_data]"][1].close()
        _raise_for_status(response, "Creating SoundCloud album")
        return response.json()

    payload = {
        "playlist": {
            "title": title,
            "sharing": sharing,
            "playlist_type": "album",
            "tracks": [{"id": track_id} for track_id in ids],
        }
    }
    if description:
        payload["playlist"]["description"] = description

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{API_BASE}/playlists",
            headers=_auth_header(access_token),
            json=payload,
        )
    _raise_for_status(response, "Creating SoundCloud album")
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
