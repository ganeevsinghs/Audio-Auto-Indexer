# SplitTracks

Split a long kirtan recording into tracks and post them to SoundCloud as a private album.

## What you need

- **Python 3.10+**
- **ffmpeg** (includes `ffprobe`)
- A SoundCloud app, only if you want to post (not needed just to try the UI)

### Install ffmpeg

macOS:

```bash
brew install ffmpeg
```

Windows: install from [ffmpeg.org](https://ffmpeg.org/download.html) and make sure `ffmpeg` is on your PATH.

## Run the site

In a terminal, from this folder:

```bash
python3 -m venv .venv
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:8000** in your browser.

## Posting to SoundCloud

1. Create an app at [soundcloud.com/you/apps](https://soundcloud.com/you/apps)
2. Set the redirect URI to exactly:

   `http://localhost:8000/api/auth/callback`

3. Click **Post to SoundCloud** and paste the Client ID and secret when asked
4. Sign in with SoundCloud

Tracks upload **private** (unlisted / secret link) and are grouped into an album in order.

## Timestamps paste format

One keertani per line: `name start end`

```
juppie 0:00 23:13
abhookie 23:58 56:20
gannu 3:09:55 3:48:38
```
