# tests/test_all.py
# -*- coding: utf-8 -*-
"""
Единый набор интеграционных тестов для ya2spotify.py.
Требуют интернет и валидные SPOTIFY_CLIENT_ID/SECRET в .env.

Запуск:
    pytest -q
"""

import re
import urllib.parse
import pytest

from ya2spotify import (
    # Яндекс -> Спотифай
    parse_yandex_track, parse_yandex_artist, parse_yandex_album,
    find_spotify_track, find_spotify_artist, find_spotify_album,
    # Спотифай -> Яндекс (by_id-обёртки сохранены для совместимости)
    spotify_get_track_by_id, spotify_get_artist_by_id, spotify_get_album_by_id,
    find_yandex_track, find_yandex_artist, find_yandex_album,
)

# --------------------------------------------------------------------------------------
# ДАННЫЕ (из ваших прошлых тестов)
# --------------------------------------------------------------------------------------

YA_TRACKS = [
    "https://music.yandex.ru/track/18769512?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/track/21806127?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/track/18878673?utm_source=web&utm_medium=copy_link",
]

YA_ARTISTS = [
    "https://music.yandex.ru/artist/31872?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/artist/221390?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/artist/11087?utm_source=web&utm_medium=copy_link",
]

YA_ALBUMS = [
    "https://music.yandex.ru/album/35627?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/album/3389007?utm_source=web&utm_medium=copy_link",
    "https://music.yandex.ru/album/4752780?utm_source=web&utm_medium=copy_link",
]

SP_TRACKS = [
    # негативный кейс (Phase Fatale — Binding by Oath): ожидаем отсутствует на Я.Музыке
    ("https://open.spotify.com/track/6nhngj5KIqYV7NDtP6hawZ?si=041e148eb2ed460e", False),
    ("https://open.spotify.com/track/4hM1v0oascRU1nIglti9fI?si=c9951cd0183d4a7c", True),
    ("https://open.spotify.com/track/4WTmtPRtIpjzgwBbQsMYyo?si=db6fecdddbe5450c", True),
]

SP_ARTISTS = [
    ("https://open.spotify.com/artist/179BpmLkQCRIoU68Co80f5?si=zeY55JOpQW-lBUwgaq0g3w", True),
    ("https://open.spotify.com/artist/0ucLPotcQNI7AViFytdhBz?si=B_Z8yNvNTGeYzFpBrLRoYw", True),
    ("https://open.spotify.com/artist/4P0dddbxPil35MNN9G2MEX?si=SYy7Z1LwT9SohyrqTECv4Q", True),
]

SP_ALBUMS = [
    ("https://open.spotify.com/album/6epuWIeu4Wq8XeYMHo1r8a?si=yntJsEjpRU-Z4oae5Dxb9Q", True),
    ("https://open.spotify.com/album/0FSsRH1jeZqKbGcHwq3UO0?si=3q8GnGygRruJ6FcJFHYq4g", True),
    ("https://open.spotify.com/album/4KZWx8zo5ym89aopr0dBIb?si=J20Z1sciT5Ktw2QJttJVrA", True),
]

# Специфические кейсы (языковые/транслит/перевод)
DOLPHIN_SP_ID = "2pktDyTJxrLJo7dL2qT1pA"  # Spotify: Dolphin (Дельфин)
DOLPHIN_YA_ID = "160530"                   # Yandex: Дельфин

KROVOSTOK_SP_TRACK = "https://open.spotify.com/track/2HP7Rr0A1UKLZu8T0ipGNl?si=c54585a41df3463d"
KROVOSTOK_EXPECTED_YA_TRACK_PREFIX = "https://music.yandex.ru/track/40037854"

# --------------------------------------------------------------------------------------
# УТИЛИТЫ
# --------------------------------------------------------------------------------------

def _extract_spotify_track_id(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    m = re.search(r"/track/([A-Za-z0-9]+)", path)
    assert m, f"Не удалось извлечь track id из {url}"
    return m.group(1)

def _extract_spotify_artist_id(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    m = re.search(r"/artist/([A-Za-z0-9]+)", path)
    assert m, f"Не удалось извлечь artist id из {url}"
    return m.group(1)

def _extract_spotify_album_id(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    m = re.search(r"/album/([A-Za-z0-9]+)", path)
    assert m, f"Не удалось извлечь album id из {url}"
    return m.group(1)

# --------------------------------------------------------------------------------------
# Яндекс → Спотифай
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", YA_TRACKS)
def test_yandex_tracks_to_spotify(spotify_token, url):
    tinfo = parse_yandex_track(url)
    sp = find_spotify_track(spotify_token, tinfo)
    assert sp is not None, f"Не нашли на Spotify: {tinfo}"
    assert sp.url.startswith("https://open.spotify.com/track/")

@pytest.mark.parametrize("url", YA_ARTISTS)
def test_yandex_artists_to_spotify(spotify_token, url):
    ainfo = parse_yandex_artist(url)
    sp = find_spotify_artist(spotify_token, ainfo.name)
    assert sp is not None, f"Не нашли артиста на Spotify: {ainfo}"
    assert sp.url.startswith("https://open.spotify.com/artist/")

@pytest.mark.parametrize("url", YA_ALBUMS)
def test_yandex_albums_to_spotify(spotify_token, url):
    alb = parse_yandex_album(url)
    sp = find_spotify_album(spotify_token, alb)
    assert sp is not None, f"Не нашли альбом на Spotify: {alb}"
    assert sp.url.startswith("https://open.spotify.com/album/")

# --------------------------------------------------------------------------------------
# Спотифай → Яндекс
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("url,should_exist", SP_TRACKS)
def test_spotify_tracks_to_yandex(spotify_token, url, should_exist):
    tid = _extract_spotify_track_id(url)
    info = spotify_get_track_by_id(spotify_token, tid)
    ya_url = find_yandex_track(info)
    if should_exist:
        assert ya_url is not None, f"Ожидали найти на Я.Музыке: {info}"
        assert ya_url.startswith("https://music.yandex.ru/track/")
    else:
        assert ya_url is None, f"Не ожидали совпадение на Я.Музыке, но вернулось: {ya_url}"

@pytest.mark.parametrize("url,should_exist", SP_ARTISTS)
def test_spotify_artists_to_yandex(spotify_token, url, should_exist):
    aid = _extract_spotify_artist_id(url)
    info = spotify_get_artist_by_id(spotify_token, aid)
    ya_url = find_yandex_artist(info)
    if should_exist:
        assert ya_url is not None, f"Ожидали найти артиста на Я.Музыке: {info}"
        assert ya_url.startswith("https://music.yandex.ru/artist/")
    else:
        assert ya_url is None

@pytest.mark.parametrize("url,should_exist", SP_ALBUMS)
def test_spotify_albums_to_yandex(spotify_token, url, should_exist):
    alid = _extract_spotify_album_id(url)
    info = spotify_get_album_by_id(spotify_token, alid)
    ya_url = find_yandex_album(info)
    if should_exist:
        assert ya_url is not None, f"Ожидали найти альбом на Я.Музыке: {info}"
        assert ya_url.startswith("https://music.yandex.ru/album/")
    else:
        assert ya_url is None

# --------------------------------------------------------------------------------------
# Специальные проверки (транслит/перевод имён)
# --------------------------------------------------------------------------------------

def test_yandex_artist_dolphin_to_spotify_exact(spotify_token):
    """
    Яндекс артист «Дельфин» должен соответствовать строго:
    https://open.spotify.com/artist/2pktDyTJxrLJo7dL2qT1pA
    """
    ya_url = "https://music.yandex.ru/artist/160530?utm_source=web&utm_medium=copy_link"
    ainfo = parse_yandex_artist(ya_url)
    sp = find_spotify_artist(spotify_token, ainfo.name)
    assert sp is not None, "Не нашли артиста «Дельфин» на Spotify"
    assert sp.id == DOLPHIN_SP_ID, f"Ожидали конкретного артиста, получили: {sp.url}"

def test_spotify_artist_dolphin_to_yandex_exact(spotify_token):
    """
    Spotify artist Dolphin (id=2pktDyTJxrLJo7dL2qT1pA) -> Яндекс «Дельфин» (160530).
    """
    sp_url = f"https://open.spotify.com/artist/{DOLPHIN_SP_ID}?si=Kiy7Y6lqR7SxGNrt_-OJoQ"
    aid = _extract_spotify_artist_id(sp_url)
    info = spotify_get_artist_by_id(spotify_token, aid)
    ya_url = find_yandex_artist(info)
    assert ya_url is not None, "Ожидали найти «Дельфина» на Я.Музыке"
    assert ya_url.startswith("https://music.yandex.ru/artist/")
    assert ya_url.rstrip("/").endswith(f"/{DOLPHIN_YA_ID}"), f"Ожидали artist/{DOLPHIN_YA_ID}, получили: {ya_url}"

def test_phase_fatale_binding_by_oath_absent(spotify_token):
    """
    Phase Fatale – Binding by Oath (Spotify): ожидаем ОТСУТСТВИЕ на Я.Музыке.
    """
    sp_url = "https://open.spotify.com/track/6nhngj5KIqYV7NDtP6hawZ?si=041e148eb2ed460e"
    tid = _extract_spotify_track_id(sp_url)
    info = spotify_get_track_by_id(spotify_token, tid)
    ya_url = find_yandex_track(info)
    assert ya_url is None, f"Не ожидали совпадение на Я.Музыке, но вернулось: {ya_url}"

def test_krovostok_track_should_match_yandex(spotify_token):
    """
    Кровосток — трек из Spotify должен находиться на Яндекс.Музыке:
      SP: https://open.spotify.com/track/2HP7Rr0A1UKLZu8T0ipGNl
      YA target: track/40037854
    """
    sp_url = "https://open.spotify.com/track/2HP7Rr0A1UKLZu8T0ipGNl?si=c54585a41df3463d"
    tid = _extract_spotify_track_id(sp_url)
    info = spotify_get_track_by_id(spotify_token, tid)
    ya_url = find_yandex_track(info)
    assert ya_url is not None, "Ожидали найти трек Кровосток на Я.Музыке"
    assert ya_url.startswith("https://music.yandex.ru/track/")
    # если хотите фиксировать ровно ID:
    # assert ya_url.rstrip("/").endswith("/40037854")