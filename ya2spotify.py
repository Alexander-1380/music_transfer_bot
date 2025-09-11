#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Any, Tuple

import requests
from dotenv import load_dotenv
from pathlib import Path

# ---------------- Models ----------------
@dataclass
class TrackInfo:
    title: str
    artists: List[str]
    album: Optional[str] = None

@dataclass
class SpotifyTrack:
    id: str
    url: str
    title: str
    artists: List[str]
    album: Optional[str]

@dataclass
class ArtistInfo:
    name: str

@dataclass
class SpotifyArtist:
    id: str
    url: str
    name: str
    popularity: int
    followers: int

@dataclass
class AlbumInfo:
    title: str
    artists: List[str]

@dataclass
class SpotifyAlbum:
    id: str
    url: str
    title: str
    artists: List[str]
    release_date: Optional[str]

# ---------------- Helpers ----------------
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
YA_HEADERS_JSON = {
    "User-Agent": UA,
    "Accept-Language": "ru,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}

def _extract_names(val: Any) -> List[str]:
    out: List[str] = []
    if isinstance(val, list):
        for a in val:
            if isinstance(a, dict):
                if isinstance(a.get("name"), str):
                    out.append(a["name"])
                elif isinstance(a.get("title"), str):
                    out.append(a["title"])
            elif isinstance(a, str):
                out.append(a)
    elif isinstance(val, dict):
        if isinstance(val.get("name"), str):
            out.append(val["name"])
        if isinstance(val.get("title"), str):
            out.append(val["title"])
        if "items" in val:
            out.extend(_extract_names(val["items"]))
    return [x for x in out if x]

def _sim(a: str, b: str) -> float:
    import unicodedata, re, string
    from difflib import SequenceMatcher
    def norm(s: str) -> str:
        if not s: return ""
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.lower()
        s = re.sub(r"\s*\([^)]*\)", " ", s)
        s = re.sub(r"\b(feat\.?|ft\.?|with)\b.*", " ", s)
        s = s.translate(str.maketrans("", "", string.punctuation + "«»„“”’‚–—"))
        s = re.sub(r"\s+", " ", s).strip()
        return s
    return SequenceMatcher(None, norm(a), norm(b)).ratio()

# ---------------- Detect URL type ----------------
def _is_track_url(path: str) -> bool:
    return bool(re.search(r"/track/\d+", path) or re.search(r"/album/\d+/track/\d+", path))

def _is_artist_url(path: str) -> bool:
    return bool(re.search(r"/artist/\d+", path))

def _is_album_only_url(path: str) -> bool:
    # Альбом без конкретного трека
    return bool(re.search(r"/album/\d+/?$", path))

# ---------------- Yandex: TRACK ----------------
def _clean_track_url_and_id(url: str) -> Tuple[str, str]:
    up = urllib.parse.urlparse(url)
    m_alt = re.search(r"/album/\d+/track/(\d+)", up.path)
    if m_alt:
        track_id = m_alt.group(1)
    else:
        m = re.search(r"/track/(\d+)", up.path)
        if not m:
            raise ValueError("Expected Yandex.Music TRACK URL like /track/<id>.")
        track_id = m.group(1)
    clean_url = urllib.parse.urlunparse((up.scheme, up.netloc, f"/track/{track_id}", "", "", ""))
    return clean_url, track_id

def _first_tracklike(obj: Any) -> Optional[TrackInfo]:
    def build(o: dict) -> Optional[TrackInfo]:
        title = o.get("title") if isinstance(o.get("title"), str) else None
        artists_v = o.get("artists") if "artists" in o else o.get("artist")
        artists = _extract_names(artists_v) if artists_v is not None else []
        album = None
        if isinstance(o.get("album"), dict):
            album = o["album"].get("title")
        elif isinstance(o.get("albums"), list) and o["albums"]:
            a0 = o["albums"][0]
            if isinstance(a0, dict):
                album = a0.get("title")
        if title and artists:
            return TrackInfo(title=title, artists=artists, album=album)
        return None

    if isinstance(obj, dict):
        t = build(obj)
        if t: return t
        if isinstance(obj.get("track"), dict):
            t = build(obj["track"])
            if t: return t
        for v in obj.values():
            if isinstance(v, dict):
                t = build(v)
                if t: return t
            elif isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        t = build(it)
                        if t: return t
    return None

def parse_yandex_track(url: str) -> TrackInfo:
    clean_url, track_id = _clean_track_url_and_id(url)
    variants = [
        f"https://music.yandex.ru/handlers/track.jsx?track={track_id}&lang=ru",
        f"https://music.yandex.ru/handlers/track.jsx?track={track_id}%3A&lang=ru",
        f"https://music.yandex.ru/handlers/track.jsx?track={track_id}:&lang=ru",
        f"https://music.yandex.ru/handlers/track.jsx?track={track_id}:0&lang=ru",
        f"https://music.yandex.ru/handlers/track.jsx?track={track_id}:1&lang=ru",
    ]
    sess = requests.Session()
    headers = dict(YA_HEADERS_JSON); headers["Referer"] = clean_url

    for u in variants:
        r = sess.get(u, headers=headers, timeout=20)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            continue
        info = _first_tracklike(data)
        if info:
            return info

    raise RuntimeError("Could not extract track data from Yandex.Music.")

# ---------------- Yandex: ARTIST ----------------
def _clean_artist_url_and_id(url: str) -> Tuple[str, str]:
    up = urllib.parse.urlparse(url)
    m = re.search(r"/artist/(\d+)", up.path)
    if not m:
        raise ValueError("Expected Yandex.Music ARTIST URL like /artist/<id>.")
    artist_id = m.group(1)
    clean_url = urllib.parse.urlunparse((up.scheme, up.netloc, f"/artist/{artist_id}", "", "", ""))
    return clean_url, artist_id

def parse_yandex_artist(url: str) -> ArtistInfo:
    clean_url, artist_id = _clean_artist_url_and_id(url)
    variants = [
        f"https://music.yandex.ru/handlers/artist.jsx?artist={artist_id}&what=artist&lang=ru",
        f"https://music.yandex.ru/handlers/artist.jsx?artist={artist_id}&what=briefInfo&lang=ru",
        f"https://music.yandex.ru/handlers/artist.jsx?artist={artist_id}&what=info&lang=ru",
        f"https://music.yandex.ru/handlers/artist.jsx?artist={artist_id}&what=tracks&lang=ru",
    ]
    headers = dict(YA_HEADERS_JSON); headers["Referer"] = clean_url

    for u in variants:
        r = requests.get(u, headers=headers, timeout=20)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            continue

        name = (
            (isinstance(data.get("artist"), dict) and data["artist"].get("name")) or
            (isinstance(data.get("result"), dict) and isinstance(data["result"].get("artist"), dict) and data["result"]["artist"].get("name")) or
            data.get("name")
        )
        if isinstance(name, str) and name.strip():
            return ArtistInfo(name=name.strip())

        tracks = data.get("tracks") or (isinstance(data.get("result"), dict) and data["result"].get("tracks")) or []
        if isinstance(tracks, list):
            for t in tracks:
                if isinstance(t, dict):
                    names = _extract_names(t.get("artists") or t.get("artist"))
                    if names:
                        return ArtistInfo(name=names[0])

    raise RuntimeError("Could not extract artist name from Yandex.Music.")

# ---------------- Yandex: ALBUM (NEW) ----------------
def _clean_album_url_and_id(url: str) -> Tuple[str, str]:
    up = urllib.parse.urlparse(url)
    m = re.search(r"/album/(\d+)", up.path)
    if not m:
        raise ValueError("Expected Yandex.Music ALBUM URL like /album/<id>.")
    album_id = m.group(1)
    clean_url = urllib.parse.urlunparse((up.scheme, up.netloc, f"/album/{album_id}", "", "", ""))
    return clean_url, album_id

def parse_yandex_album(url: str) -> AlbumInfo:
    clean_url, album_id = _clean_album_url_and_id(url)
    variants = [
        f"https://music.yandex.ru/handlers/album.jsx?album={album_id}&lang=ru",
        f"https://music.yandex.ru/handlers/album.jsx?album={album_id}&what=album&lang=ru",
        f"https://music.yandex.ru/handlers/album.jsx?album={album_id}&what=info&lang=ru",
        f"https://music.yandex.ru/handlers/album.jsx?albumId={album_id}&lang=ru",
    ]
    headers = dict(YA_HEADERS_JSON); headers["Referer"] = clean_url

    for u in variants:
        r = requests.get(u, headers=headers, timeout=20)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            continue

        # Популярные места: data['album'] / data['result']['album'] / верхний уровень
        album_obj = None
        if isinstance(data.get("album"), dict):
            album_obj = data["album"]
        elif isinstance(data.get("result"), dict) and isinstance(data["result"].get("album"), dict):
            album_obj = data["result"]["album"]
        else:
            album_obj = data if isinstance(data, dict) and "title" in data else None

        if isinstance(album_obj, dict):
            title = album_obj.get("title") if isinstance(album_obj.get("title"), str) else None
            artists = _extract_names(album_obj.get("artists") or album_obj.get("artist"))
            if title and artists:
                return AlbumInfo(title=title, artists=artists)

        # fallback: берём из первого трека альбома
        tracks = data.get("tracks") or (isinstance(data.get("result"), dict) and data["result"].get("tracks")) or []
        if isinstance(tracks, list) and tracks:
            t0 = tracks[0]
            if isinstance(t0, dict):
                title = album_obj.get("title") if isinstance(album_obj, dict) else None
                artists = _extract_names(t0.get("artists") or t0.get("artist")) or []
                if title and artists:
                    return AlbumInfo(title=title, artists=artists)

    raise RuntimeError("Could not extract album data from Yandex.Music.")

# ---------------- Spotify: search ----------------
def get_spotify_token(client_id: str, client_secret: str) -> str:
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def spotify_search_tracks(token: str, q: str, limit: int = 10) -> List[SpotifyTrack]:
    params = {"q": q, "type": "track", "limit": limit}
    r = requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}"},
                     params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("tracks", {}).get("items", [])
    out: List[SpotifyTrack] = []
    for it in items:
        out.append(SpotifyTrack(
            id=it["id"],
            url=f"https://open.spotify.com/track/{it['id']}",
            title=it["name"],
            artists=[a["name"] for a in it.get("artists", [])],
            album=(it.get("album") or {}).get("name"),
        ))
    return out

def spotify_search_artists(token: str, q: str, limit: int = 10) -> List[SpotifyArtist]:
    params = {"q": q, "type": "artist", "limit": limit}
    r = requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}"},
                     params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("artists", {}).get("items", [])
    out: List[SpotifyArtist] = []
    for it in items:
        out.append(SpotifyArtist(
            id=it["id"],
            url=f"https://open.spotify.com/artist/{it['id']}",
            name=it["name"],
            popularity=int(it.get("popularity") or 0),
            followers=int(((it.get("followers") or {}).get("total")) or 0),
        ))
    return out

def spotify_search_albums(token: str, q: str, limit: int = 10) -> List[SpotifyAlbum]:
    params = {"q": q, "type": "album", "limit": limit}
    r = requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}"},
                     params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("albums", {}).get("items", [])
    out: List[SpotifyAlbum] = []
    for it in items:
        out.append(SpotifyAlbum(
            id=it["id"],
            url=f"https://open.spotify.com/album/{it['id']}",
            title=it["name"],
            artists=[a["name"] for a in it.get("artists", [])],
            release_date=it.get("release_date"),
        ))
    return out

# ---------------- Spotify: matchers ----------------
def find_spotify_track(token: str, target: TrackInfo) -> Optional[SpotifyTrack]:
    main_artist = target.artists[0] if target.artists else ""
    queries = [
        f'track:"{target.title}" artist:"{main_artist}"',
        f'"{target.title}" {main_artist}'.strip(),
        f'track:"{target.title}"',
    ]
    candidates: List[SpotifyTrack] = []
    for q in queries:
        res = spotify_search_tracks(token, q, limit=10)
        candidates.extend(res)
        if res:
            break
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda c: 0.6 * _sim(c.title, target.title)
                    + 0.35 * max((_sim(a1, a2) for a1 in c.artists for a2 in target.artists), default=0.0)
                    + 0.05 * _sim(c.album or "", target.album or "")
    )
    score = 0.6 * _sim(best.title, target.title) \
          + 0.35 * max((_sim(a1, a2) for a1 in best.artists for a2 in target.artists), default=0.0) \
          + 0.05 * _sim(best.album or "", target.album or "")
    return best if score >= 0.62 else None

def find_spotify_artist(token: str, name: str) -> Optional[SpotifyArtist]:
    cands = spotify_search_artists(token, name, limit=10)
    if not cands:
        return None
    def score(a: SpotifyArtist) -> Tuple[float, int, int]:
        return (_sim(a.name, name), a.popularity, a.followers)
    return sorted(cands, key=score, reverse=True)[0]

def find_spotify_album(token: str, target: AlbumInfo) -> Optional[SpotifyAlbum]:
    main_artist = target.artists[0] if target.artists else ""
    queries = [
        f'album:"{target.title}" artist:"{main_artist}"',
        f'"{target.title}" {main_artist}'.strip(),
        f'album:"{target.title}"',
    ]
    candidates: List[SpotifyAlbum] = []
    for q in queries:
        res = spotify_search_albums(token, q, limit=10)
        candidates.extend(res)
        if res:
            break
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda a: 0.7 * _sim(a.title, target.title)
                    + 0.3 * max((_sim(n1, n2) for n1 in a.artists for n2 in target.artists), default=0.0)
    )
    score = 0.7 * _sim(best.title, target.title) \
          + 0.3 * max((_sim(n1, n2) for n1 in best.artists for n2 in target.artists), default=0.0)
    return best if score >= 0.66 else None

# ---------------- Main ----------------
def main():
    # .env рядом со скриптом
    load_dotenv(Path(__file__).with_name(".env"))

    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip().strip('"').strip("'")
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip().strip('"').strip("'")
    if not client_id or not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not found in .env")

    ya_url = input("Enter Yandex.Music URL (track / artist / album): ").strip()
    path = urllib.parse.urlparse(ya_url).path
    token = get_spotify_token(client_id, client_secret)

    if _is_track_url(path):
        # Яндекс трек → Спотифай трек
        tinfo = parse_yandex_track(ya_url)
        sp_t = find_spotify_track(token, tinfo)

        print("\nParsed from Yandex.Music (Track):")
        print(f"  Title: {tinfo.title}")
        print(f"  Artist(s): {', '.join(tinfo.artists) if tinfo.artists else '-'}")
        print(f"  Album: {tinfo.album or '-'}")

        if sp_t:
            print("\nFound on Spotify (Track):")
            print(f"  {sp_t.title} - {', '.join(sp_t.artists)}")
            print(f"  Album: {sp_t.album or '-'}")
            print(f"  Link: {sp_t.url}")
        else:
            print("\nNo such track on Spotify.")

    elif _is_artist_url(path):
        # Яндекс артист → Спотифай артист
        ainfo = parse_yandex_artist(ya_url)
        sp_a = find_spotify_artist(token, ainfo.name)

        print("\nParsed from Yandex.Music (Artist):")
        print(f"  Name: {ainfo.name}")

        if sp_a:
            print("\nFound on Spotify (Artist):")
            print(f"  {sp_a.name}")
            print(f"  Link: https://open.spotify.com/artist/{sp_a.id}")
        else:
            print("\nNo such artist on Spotify.")

    elif _is_album_only_url(path):
        # Яндекс альбом → Спотифай альбом
        alb = parse_yandex_album(ya_url)
        sp_alb = find_spotify_album(token, alb)

        print("\nParsed from Yandex.Music (Album):")
        print(f"  Title: {alb.title}")
        print(f"  Artist(s): {', '.join(alb.artists) if alb.artists else '-'}")

        if sp_alb:
            print("\nFound on Spotify (Album):")
            print(f"  {sp_alb.title} - {', '.join(sp_alb.artists)}")
            if sp_alb.release_date:
                print(f"  Release: {sp_alb.release_date}")
            print(f"  Link: {sp_alb.url}")
        else:
            print("\nNo such album on Spotify.")

    else:
        raise ValueError("Unsupported Yandex.Music URL. Provide /track/<id>, /artist/<id>, or /album/<id>.")

if __name__ == "__main__":
    main()