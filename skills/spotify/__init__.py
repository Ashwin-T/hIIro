"""Spotify playback skill."""
from __future__ import annotations
from typing import Optional

TOOLS = [
    {"name": "spotify_play", "description": "Play a song/album/playlist on Spotify.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Search term e.g. 'Bohemian Rhapsody'"},
         "type": {"type": "string", "description": "track|album|playlist|artist", "default": "track"}},
         "required": ["query"]}},
    {"name": "spotify_control", "description": "Control Spotify: pause, resume, skip, previous, volume.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "description": "pause|resume|next|previous|volume"},
         "volume": {"type": "integer", "description": "0-100 (for volume action)"}},
         "required": ["action"]}},
    {"name": "spotify_now_playing", "description": "What's currently playing on Spotify.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _make(client_id, client_secret, redirect_uri):
    if not client_id or not client_secret:
        def _nope(**_): return {"error": "Spotify not configured"}
        return [_nope, _nope, _nope]

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri,
            scope="user-read-playback-state user-modify-playback-state user-read-currently-playing"))
    except Exception as e:
        def _err(**_): return {"error": f"Spotify init: {e}"}
        return [_err, _err, _err]

    def play(query: str, type: str = "track") -> dict:
        try:
            items = sp.search(q=query, type=type, limit=1).get(f"{type}s", {}).get("items", [])
            if not items: return {"error": f"Nothing found for '{query}'"}
            uri = items[0]["uri"]
            if type == "track": sp.start_playback(uris=[uri])
            else: sp.start_playback(context_uri=uri)
            return {"playing": items[0].get("name", query), "artist": items[0].get("artists", [{}])[0].get("name", "")}
        except Exception as e: return {"error": str(e)}

    def control(action: str, volume: Optional[int] = None) -> dict:
        try:
            a = action.lower()
            if a == "pause": sp.pause_playback()
            elif a in {"resume","play"}: sp.start_playback()
            elif a in {"next","skip"}: sp.next_track()
            elif a == "previous": sp.previous_track()
            elif a == "volume" and volume is not None: sp.volume(max(0, min(100, volume)))
            return {"ok": True, "action": a}
        except Exception as e: return {"error": str(e)}

    def now_playing() -> dict:
        try:
            c = sp.current_playback()
            if not c or not c.get("item"): return {"status": "nothing playing"}
            i = c["item"]
            return {"track": i["name"], "artist": i["artists"][0]["name"],
                    "album": i["album"]["name"], "playing": c["is_playing"]}
        except Exception as e: return {"error": str(e)}

    return [play, control, now_playing]


def build(cfg) -> list[tuple[dict, object]]:
    return list(zip(TOOLS, _make(cfg.spotify_client_id, cfg.spotify_client_secret, cfg.spotify_redirect_uri)))
