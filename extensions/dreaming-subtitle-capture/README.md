# Dreaming Subtitle Capture

Chrome/Edge extension for personal study. It copies subtitle/caption text from the currently open Dreaming video page when the subtitles are available in the browser.

## Install

1. Open `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select this folder:
   `/Users/enes/Desktop/shadowing/extensions/dreaming-subtitle-capture`

## Use

1. Open `https://app.dreaming.com` and sign in.
2. Open a video.
3. Turn subtitles/captions on if the player has them.
4. Click the extension icon, then `Şimdi görüneni kopyala`.
5. If YouTube exposes a full caption track, the whole transcript is copied immediately.
6. If only visible captions are available, click `Kayda başla`, play the video while captions are visible, then click `Durdur + kopyala`.

## Full YouTube Transcript Fallback

If the extension finds a YouTube URL but cannot copy the full transcript in-browser, try the local `yt-dlp` helper:

```bash
python3 scripts/youtube_transcript.py "YOUTUBE_URL_OR_ID" --lang es,en --cookies-from-browser chrome
```

It writes `.txt` and `.json` transcript files under:

```text
private_data/youtube_transcripts/
```

If no subtitle/caption track exists for that video, the extension cannot create one.
