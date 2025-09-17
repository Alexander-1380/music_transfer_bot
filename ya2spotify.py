#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Any, Tuple, Dict, Callable

import requests
from pathlib import Path
from dotenv import load_dotenv

# --- optional deps ---
try:
    from transliterate import translit  # ru <-> lat
except Exception:
    translit = None

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:
        return s  # safe fallback

# =========================
# Models
# =========================
@dataclass
class TrackInfo:
    title: str
    artists: List[str]
    album: Optional[str] = None

@dataclass
class ArtistInfo:
    name: str
    top_tracks: Optional[List[str]] = None  # для cross-check

@dataclass
class AlbumInfo:
    title: str
    artists: List[str]

@dataclass
class SpotifyTrack:
    id: str
    url: str
    title: str
    artists: List[str]
    album: Optional[str]

@dataclass
class SpotifyArtist:
    id: str
    url: str
    name: str
    popularity: int
    followers: int

@dataclass
class SpotifyAlbum:
    id: str
    url: str
    title: str
    artists: List[str]
    release_date: Optional[str]

# =========================
# Consts & helpers
# =========================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
YA_HEADERS_JSON = {
    "User-Agent": UA,
    "Accept-Language": "ru,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}
SP_HEADERS = {"User-Agent": UA}

def _retry(fn: Callable[[], requests.Response], tries: int = 3, sleep: float = 0.4) -> Optional[requests.Response]:
    for i in range(tries):
        try:
            r = fn()
            return r
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(sleep)
    return None

def _extract_names(val: Any) -> List[str]:
    """Из объектов Яндекса вытаскивает имена артистов/титулы."""
    out: List[str] = []
    if isinstance(val, list):
        for a in val:
            if isinstance(a, dict):
                n = a.get("name") or a.get("title")
                if isinstance(n, str) and n:
                    out.append(n)
            elif isinstance(a, str) and a:
                out.append(a)
    elif isinstance(val, dict):
        n = val.get("name") or val.get("title")
        if isinstance(n, str) and n:
            out.append(n)
        if "items" in val:
            out.extend(_extract_names(val["items"]))
    return [x for x in out if x]

def _norm(s: str) -> str:
    import unicodedata, string
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s*\([^)]*\)", " ", s)
    s = re.sub(r"\b(feat\.?|ft\.?|with)\b.*", " ", s)
    s = s.translate(str.maketrans("", "", string.punctuation + "«»„“”’‚–—"))
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _sim(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

def _token_overlap(a: str, b: str) -> float:
    ta = set([t for t in _norm(a).split() if t])
    tb = set([t for t in _norm(b).split() if t])
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def _ru2lat(name: str) -> str:
    if not name:
        return name
    s = name
    if translit:
        try:
            s = translit(s, 'ru', reversed=True)
        except Exception:
            pass
    s = unidecode(s)
    return " ".join(s.split())

def _variants_for_artist_name(name: str) -> List[str]:
    """Оригинал + транслит + короткая версия без скобок."""
    vs = []
    base = " ".join((name or "").split())
    if base:
        vs.append(base)
        lat = _ru2lat(base)
        if lat and lat.lower() != base.lower():
            vs.append(lat)
    short = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
    if short and short.lower() not in [v.lower() for v in vs]:
        vs.append(short)
    return list(dict.fromkeys(vs))

# для некоторых кейсов англ-алиасы ручкой
ARTIST_EN_ALIASES: Dict[str, List[str]] = {
    "дельфин": ["dolphin"],
    "кровосток": ["krovostok"],  # обычно транслит, но на всякий
}

# =========================
# URL type checks
# =========================
def _is_track_url(path: str) -> bool:
    return bool(re.search(r"/track/\d+", path) or re.search(r"/album/\d+/track/\d+", path))

def _is_artist_url(path: str) -> bool:
    return bool(re.search(r"/artist/\d+", path))

def _is_album_only_url(path: str) -> bool:
    return bool(re.search(r"/album/\d+/?$", path))

def _is_spotify_track(path: str) -> Optional[str]:
    m = re.search(r"/track/([A-Za-z0-9]+)", path)
    return m.group(1) if m else None

def _is_spotify_artist(path: str) -> Optional[str]:
    m = re.search(r"/artist/([A-Za-z0-9]+)", path)
    return m.group(1) if m else None

def _is_spotify_album(path: str) -> Optional[str]:
    m = re.search(r"/album/([A-Za-z0-9]+)", path)
    return m.group(1) if m else None

# =========================
# Yandex parsers
# =========================
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
            t = build(obj["track"]); 
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
        r = _retry(lambda: sess.get(u, headers=headers, timeout=20))
        if not r or r.status_code != 200:
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            continue
        info = _first_tracklike(data)
        if info:
            return info
    raise RuntimeError("Could not extract track data from Yandex.Music.")

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
        f"https://music.yandex.ru/handlers/artist.jsx?artist={artist_id}&what=tracks&lang=ru",
    ]
    headers = dict(YA_HEADERS_JSON); headers["Referer"] = clean_url

    for u in variants:
        r = _retry(lambda: requests.get(u, headers=headers, timeout=20))
        if not r or r.status_code != 200:
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
        # из треков
        tracks = data.get("tracks") or (isinstance(data.get("result"), dict) and data["result"].get("tracks")) or []
        if isinstance(tracks, list):
            for t in tracks:
                if isinstance(t, dict):
                    names = _extract_names(t.get("artists") or t.get("artist"))
                    if names:
                        return ArtistInfo(name=names[0])
    raise RuntimeError("Could not extract artist name from Yandex.Music.")

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
        r = _retry(lambda: requests.get(u, headers=headers, timeout=20))
        if not r or r.status_code != 200:
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            continue

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

        tracks = data.get("tracks") or (isinstance(data.get("result"), dict) and data["result"].get("tracks")) or []
        if isinstance(tracks, list) and tracks:
            t0 = tracks[0]
            if isinstance(t0, dict):
                title = album_obj.get("title") if isinstance(album_obj, dict) else None
                artists = _extract_names(t0.get("artists") or t0.get("artist")) or []
                if title and artists:
                    return AlbumInfo(title=title, artists=artists)

    raise RuntimeError("Could not extract album data from Yandex.Music.")

# =========================
# Spotify API
# =========================
def get_spotify_token(client_id: str, client_secret: str) -> str:
    r = _retry(lambda: requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=20,
    ))
    if not r:
        raise RuntimeError("No response from Spotify token endpoint")
    r.raise_for_status()
    return r.json()["access_token"]

def _sp_get(endpoint: str, token: str, params=None) -> dict:
    r = _retry(lambda: requests.get(
        f"https://api.spotify.com/v1/{endpoint}",
        headers={"Authorization": f"Bearer {token}", **SP_HEADERS},
        params=params or {},
        timeout=20,
    ))
    if not r:
        raise RuntimeError(f"Spotify GET {endpoint} failed without response")
    r.raise_for_status()
    return r.json()

def spotify_search_tracks(token: str, q: str, limit: int = 10) -> List[SpotifyTrack]:
    params = {"q": q, "type": "track", "limit": limit}
    r = _retry(lambda: requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}", **SP_HEADERS},
                     params=params, timeout=20))
    if not r:
        return []
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
    r = _retry(lambda: requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}", **SP_HEADERS},
                     params=params, timeout=20))
    if not r:
        return []
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
    r = _retry(lambda: requests.get("https://api.spotify.com/v1/search",
                     headers={"Authorization": f"Bearer {token}", **SP_HEADERS},
                     params=params, timeout=20))
    if not r:
        return []
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

def spotify_track_by_id(sp_id: str, token: str) -> TrackInfo:
    j = _sp_get(f"tracks/{sp_id}", token)
    title = j["name"]
    artists = [a["name"] for a in j.get("artists", [])]
    album = (j.get("album") or {}).get("name")
    return TrackInfo(title=title, artists=artists, album=album)

def spotify_artist_by_id(sp_id: str, token: str) -> ArtistInfo:
    j = _sp_get(f"artists/{sp_id}", token)
    # подгрузим топ-треки для шага 2/3
    tops = _sp_get(f"artists/{sp_id}/top-tracks", token, params={"market": "US"}).get("tracks", [])
    top_names = [t.get("name") for t in tops if isinstance(t, dict) and t.get("name")]
    return ArtistInfo(name=j["name"], top_tracks=top_names[:10])

def spotify_album_by_id(sp_id: str, token: str) -> AlbumInfo:
    j = _sp_get(f"albums/{sp_id}", token)
    title = j["name"]
    artists = [a["name"] for a in j.get("artists", [])]
    return AlbumInfo(title=title, artists=artists)

# Thin wrappers to keep tests compatibility
def spotify_get_track_by_id(token: str, track_id: str): return spotify_track_by_id(track_id, token)
def spotify_get_artist_by_id(token: str, artist_id: str): return spotify_artist_by_id(artist_id, token)
def spotify_get_album_by_id(token: str, album_id: str):   return spotify_album_by_id(album_id, token)

# =========================
# Yandex search helpers
# =========================
def _ya_search_json(query: str) -> Optional[Dict[str, Any]]:
    endpoints = [
        "https://music.yandex.ru/handlers/search.jsx",
        "https://music.yandex.ru/handlers/music-search.jsx",
    ]
    for ep in endpoints:
        try:
            r = _retry(lambda: requests.get(
                ep, headers=YA_HEADERS_JSON,
                params={"text": query, "type": "all", "page": 0, "lang": "ru"},
                timeout=20
            ))
            if r and r.status_code == 200 and r.headers.get("content-type","").startswith("application/json"):
                return r.json()
        except Exception:
            continue
    return None

def _ya_search_html_fallback(query: str) -> Optional[Dict[str, Any]]:
    url = "https://music.yandex.ru/search"
    try:
        r = _retry(lambda: requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.9"},
                         params={"text": query}, timeout=20))
        if not r or r.status_code != 200:
            return None
        html = r.text
        import re as _re, json as _json
        json_candidates = _re.findall(r'>\s*({.*"tracks"\s*:\s*{.*?}}\s*})\s*<', html, flags=_re.S)
        if not json_candidates:
            json_candidates = _re.findall(r'>\s*({.*"serpList"\s*:\s*\[.*?]\s*}.*?)\s*<', html, flags=_re.S)
        if json_candidates:
            blob = max(json_candidates, key=len)
            try:
                return _json.loads(blob)
            except Exception:
                pass
    except Exception:
        pass
    return None

# =========================
# Matchers: Yandex -> Spotify
# =========================
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

    def score(c: SpotifyTrack) -> float:
        # жёстче фильтруем: по названию требуем приличное пересечение токенов
        title_sim = _sim(c.title, target.title)
        title_tok = _token_overlap(c.title, target.title)
        art_sim = max((_sim(a1, a2) for a1 in c.artists for a2 in target.artists), default=0.0)
        alb_sim = _sim(c.album or "", target.album or "")
        # hard filters против случайных совпадений:
        if title_tok < 0.45:
            return -1.0
        return 0.6 * title_sim + 0.3 * art_sim + 0.1 * alb_sim

    best = max(candidates, key=score)
    if score(best) < 0.62:
        return None
    return best

def find_spotify_artist(token: str, name: str) -> Optional[SpotifyArtist]:
    """
    Для артистов на выходе берём только точные результаты по имени (ориг/транслит/алиас),
    затем дополнительно убеждаемся, что топ-треки найденного артиста существуют на Я.Музыке
    хотя бы два раза — если сможем это проверить.
    """
    # 1) точное совпадение имени
    exact = [a for a in spotify_search_artists(token, name, limit=10) if _norm(a.name) == _norm(name)]
    if exact:
        return sorted(exact, key=lambda x: (x.popularity, x.followers), reverse=True)[0]

    # 2) транслит
    name_lat = _ru2lat(name)
    if name_lat and _norm(name_lat) != _norm(name):
        translit_hits = [a for a in spotify_search_artists(token, name_lat, limit=10) if _norm(a.name) == _norm(name_lat)]
        if translit_hits:
            return sorted(translit_hits, key=lambda x: (x.popularity, x.followers), reverse=True)[0]

    # 3) англ-алиасы
    aliases = ARTIST_EN_ALIASES.get(_norm(name), [])
    for al in aliases:
        alias_hits = [a for a in spotify_search_artists(token, al, limit=10) if _norm(a.name) == _norm(al)]
        if alias_hits:
            return sorted(alias_hits, key=lambda x: (x.popularity, x.followers), reverse=True)[0]

    return None

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

    def score(a: SpotifyAlbum) -> float:
        t = 0.7 * _sim(a.title, target.title)
        ar = 0.3 * max((_sim(n1, n2) for n1 in a.artists for n2 in target.artists), default=0.0)
        # жёсткая проверка токенов по названию
        if _token_overlap(a.title, target.title) < 0.5:
            return -1.0
        return t + ar

    best = max(candidates, key=score)
    if score(best) < 0.66:
        return None
    return best

# =========================
# Matchers: Spotify -> Yandex
# =========================
def find_yandex_track(info: TrackInfo) -> Optional[str]:
    title = info.title or ""
    artists = info.artists or []
    album = info.album or ""

    # запросы
    queries_raw = []
    if artists:
        queries_raw += [
            f'{title} {artists[0]} {album}'.strip(),
            f'{title} {artists[0]}'.strip(),
            f'{title} {" ".join(artists)} {album}'.strip(),
            f'{title} {" ".join(artists)}'.strip(),
        ]
    queries_raw += [f'{title} {album}'.strip(), title.strip()]

    seen = set(); queries = []
    for q in queries_raw:
        qn = " ".join(q.split())
        if qn and qn.lower() not in seen:
            seen.add(qn.lower()); queries.append(qn)

    def score_track(t: dict) -> float:
        t_title = t.get("title") or ""
        t_artists = _extract_names(t.get("artists") or [])
        t_album = (t.get("albums") or [{}])[0].get("title") if t.get("albums") else ""
        title_tok = _token_overlap(info.title, t_title)
        if title_tok < 0.5:  # отсечём «Bind You by Oath»
            return -1.0
        art_sim = max((_sim(a, x) for a in info.artists for x in t_artists), default=0.0)
        if art_sim < 0.55:  # требуем приличное совпадение артистов
            return -1.0
        return 0.6 * _sim(info.title, t_title) + 0.3 * art_sim + 0.1 * _sim(info.album or "", t_album or "")

    # JSON endpoints
    for q in queries:
        j = _ya_search_json(q)
        tracks = None
        if j:
            tracks = ((j.get("tracks") or {}).get("items")) or []
            if not tracks and "best" in j and (j["best"] or {}).get("type") == "track":
                tracks = [j["best"]["result"]]
        if tracks:
            best = max(tracks, key=score_track)
            if score_track(best) >= 0:
                tid = str(best.get("id") or "")
                if ":" in tid: tid = tid.split(":")[-1]
                if tid.isdigit():
                    return f"https://music.yandex.ru/track/{tid}"

    # HTML fallback
    for q in queries:
        j = _ya_search_html_fallback(q)
        tracks = None
        if isinstance(j, dict):
            if "tracks" in j and isinstance(j["tracks"], dict):
                tracks = j["tracks"].get("items") or []
            if (not tracks) and "best" in j and (j["best"] or {}).get("type") == "track":
                tracks = [j["best"]["result"]]
        if tracks:
            best = max(tracks, key=score_track)
            if score_track(best) >= 0:
                tid = str(best.get("id") or "")
                if ":" in tid: tid = tid.split(":")[-1]
                if tid.isdigit():
                    return f"https://music.yandex.ru/track/{tid}"

    return None

def _artist_top_overlap(spotify_top: List[str], ya_artist_name: str) -> int:
    """Считаем, сколько из spotify_top находятся в выдаче Я.Музыки при запросе '<трек> <имя артиста>'."""
    hits = 0
    for t in (spotify_top or [])[:5]:  # 5 хватит
        q = f"{t} {ya_artist_name}"
        j = _ya_search_json(q)
        if not j:
            continue
        tr = ((j.get("tracks") or {}).get("items")) or []
        if tr:
            hits += 1
    return hits

def find_yandex_artist(info: ArtistInfo) -> Optional[str]:
    """
    Жёсткая логика из 3 шагов:
    1) точное имя на кириллице/латинице;
    2) транслит → нужен overlap >= 2 топ-треков;
    3) англ-алиасы → нужен overlap >= 2 топ-треков.
    Никакого «похожести имени».
    """
    name = info.name
    variants = _variants_for_artist_name(name)
    all_candidates: List[dict] = []

    def ya_artists_from_query(q: str) -> List[dict]:
        j = _ya_search_json(q)
        res = []
        if j:
            res = ((j.get("artists") or {}).get("items")) or []
            if not res and "best" in j and (j["best"] or {}).get("type") == "artist":
                res = [j["best"]["result"]]
        return res or []

    # 1) точное совпадение имени
    for q in [name]:
        cand = ya_artists_from_query(q)
        exact = [a for a in cand if _norm(a.get("name") or "") == _norm(q)]
        if exact:
            aid = str(exact[0].get("id") or "")
            return f"https://music.yandex.ru/artist/{aid}" if aid else None

    # 2) транслит
    name_lat = _ru2lat(name)
    if name_lat and _norm(name_lat) != _norm(name):
        cand = ya_artists_from_query(name_lat)
        exact = [a for a in cand if _norm(a.get("name") or "") == _norm(name_lat)]
        if exact:
            if info.top_tracks:
                ov = _artist_top_overlap(info.top_tracks, exact[0].get("name") or "")
                if ov >= 2:
                    aid = str(exact[0].get("id") or "")
                    return f"https://music.yandex.ru/artist/{aid}" if aid else None

    # 3) англ-алиасы
    aliases = ARTIST_EN_ALIASES.get(_norm(name), [])
    for al in aliases:
        cand = ya_artists_from_query(al)
        exact = [a for a in cand if _norm(a.get("name") or "") == _norm(al)]
        if exact:
            if info.top_tracks:
                ov = _artist_top_overlap(info.top_tracks, exact[0].get("name") or "")
                if ov >= 2:
                    aid = str(exact[0].get("id") or "")
                    return f"https://music.yandex.ru/artist/{aid}" if aid else None

    return None

def find_yandex_album(info: AlbumInfo) -> Optional[str]:
    q = " ".join([info.title] + info.artists)
    j = _ya_search_json(q)
    if not j:
        j = _ya_search_html_fallback(q)
        if not j:
            return None
    albums = ((j.get("albums") or {}).get("items")) or []
    if not albums and "best" in j and (j["best"] or {}).get("type") == "album":
        albums = [j["best"]["result"]]
    if not albums:
        return None

    def score(a: dict) -> float:
        t = a.get("title") or ""
        ar = _extract_names(a.get("artists") or [])
        if _token_overlap(info.title, t) < 0.5:
            return -1.0
        return 0.7 * _sim(info.title, t) + 0.3 * max((_sim(x, y) for x in info.artists for y in ar), default=0.0)

    best = max(albums, key=score)
    if score(best) < 0:
        return None
    aid = str(best.get("id") or "")
    return f"https://music.yandex.ru/album/{aid}" if aid else None

# =========================
# High-level resolve (для бота)
# =========================
def resolve_url(url: str, client_id: Optional[str] = None, client_secret: Optional[str] = None,
                market: Optional[str] = None) -> Dict[str, Any]:
    """
    Универсальный роутер:
      - Яндекс (track/artist/album) -> Spotify (со ссылкой)
      - Spotify (track/artist/album) -> Яндекс (со ссылкой)
    """
    up = urllib.parse.urlparse(url)
    host = (up.netloc or "").lower().replace("www.", "")
    path = up.path or ""

    # токен Spotify
    token = None
    if client_id and client_secret:
        try:
            token = get_spotify_token(client_id, client_secret)
        except Exception:
            pass

    # Spotify → Yandex
    if "open.spotify.com" in host:
        if not token:
            return {"ok": False, "error": "Нет SPOTIFY_CLIENT_ID/SECRET в .env — не могу обработать Spotify-ссылку."}

        sid = _is_spotify_track(path)
        if sid:
            try:
                sp_info = spotify_track_by_id(sid, token)
                ya = find_yandex_track(sp_info)
                if ya:
                    return {"ok": True, "source": {"service":"spotify","type":"track","info": sp_info},
                            "target": {"service":"yandex","type":"track","url": ya,
                                       "title": sp_info.title, "artists": sp_info.artists, "album": sp_info.album}}
                if sp_info.album:
                    alb_info = AlbumInfo(title=sp_info.album, artists=sp_info.artists or [])
                    ya_alb = find_yandex_album(alb_info)
                    if ya_alb:
                        return {"ok": True, "source": {"service":"spotify","type":"track","info": sp_info},
                                "target": {"service":"yandex","type":"album","url": ya_alb,
                                           "title": alb_info.title, "artists": alb_info.artists}}
                return {"ok": False, "error": "Трека нет в Яндекс.Музыке."}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Spotify track: {e!r}"}

        sid = _is_spotify_artist(path)
        if sid:
            try:
                ainfo = spotify_artist_by_id(sid, token)
                ya = find_yandex_artist(ainfo)
                if not ya:
                    return {"ok": False, "error": "Артиста нет в Яндекс.Музыке."}
                return {"ok": True, "source": {"service":"spotify","type":"artist","info": ainfo},
                        "target": {"service":"yandex","type":"artist","url": ya, "name": ainfo.name}}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Spotify artist: {e!r}"}

        sid = _is_spotify_album(path)
        if sid:
            try:
                alb_info = spotify_album_by_id(sid, token)
                ya = find_yandex_album(alb_info)
                if not ya:
                    return {"ok": False, "error": "Альбома нет в Яндекс.Музыке."}
                return {"ok": True, "source": {"service":"spotify","type":"album","info": alb_info},
                        "target": {"service":"yandex","type":"album","url": ya,
                                   "title": alb_info.title, "artists": alb_info.artists}}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Spotify album: {e!r}"}

        return {"ok": False, "error": "Не удалось распознать тип ссылки Spotify."}

    # Yandex → Spotify
    if "music.yandex" in host:
        if not token:
            return {"ok": False, "error": "Нет SPOTIFY_CLIENT_ID/SECRET в .env — не могу искать на Spotify."}

        if _is_track_url(path):
            try:
                tinfo = parse_yandex_track(url)
                sp_t = find_spotify_track(token, tinfo)
                if not sp_t:
                    return {"ok": False, "error": "Трека нет в Spotify."}
                return {"ok": True, "source": {"service":"yandex","type":"track","info": tinfo},
                        "target": {"service":"spotify","type":"track","url": sp_t.url,
                                   "title": sp_t.title, "artists": sp_t.artists, "album": sp_t.album}}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Яндекс трека: {e!r}"}

        if _is_artist_url(path):
            try:
                ainfo = parse_yandex_artist(url)
                # для шага 2/3 нам нужен кандидат на Spotify, но твоя логика для Y->SP требует точных имён
                sp_a = find_spotify_artist(token, ainfo.name)
                if not sp_a:
                    return {"ok": False, "error": "Артиста нет в Spotify."}
                return {"ok": True, "source": {"service":"yandex","type":"artist","info": ainfo},
                        "target": {"service":"spotify","type":"artist","url": sp_a.url, "name": sp_a.name}}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Яндекс артиста: {e!r}"}

        if _is_album_only_url(path):
            try:
                alb = parse_yandex_album(url)
                sp_alb = find_spotify_album(token, alb)
                if not sp_alb:
                    return {"ok": False, "error": "Альбома нет в Spotify."}
                return {"ok": True, "source": {"service":"yandex","type":"album","info": alb},
                        "target": {"service":"spotify","type":"album","url": sp_alb.url,
                                   "title": sp_alb.title, "artists": sp_alb.artists}}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка обработки Яндекс альбома: {e!r}"}

        return {"ok": False, "error": "Unsupported Yandex.Music URL. Provide /track/<id>, /artist/<id>, or /album/<id>."}

    return {"ok": False, "error": "Не удалось определить сервис/тип ссылки."}

# =========================
# CLI (на месте)
# =========================
def main():
    load_dotenv(Path(__file__).with_name(".env"))
    cid = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip().strip('"').strip("'")
    csec = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip().strip('"').strip("'")
    if not cid or not csec:
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not found in .env")

    url = input("Enter music URL (Yandex or Spotify): ").strip()
    res = resolve_url(url, cid, csec)
    if not res.get("ok"):
        print("ERROR:", res.get("error")); return
    src = res["source"]; dst = res["target"]
    print("\nParsed:")
    print(f"  Source: {src['service']} / {src['type']}")
    info = src["info"]
    if isinstance(info, TrackInfo):
        print(f"  Title: {info.title}\n  Artist(s): {', '.join(info.artists)}")
        if info.album: print(f"  Album: {info.album}")
    elif isinstance(info, ArtistInfo):
        print(f"  Name: {info.name}")
    elif isinstance(info, AlbumInfo):
        print(f"  Album: {info.title}")
        if info.artists: print(f"  Artist(s): {', '.join(info.artists)}")
    print("\nFound:")
    print(f"  {dst['service']} / {dst['type']} -> {dst.get('url')}")

if __name__ == "__main__":
    main()