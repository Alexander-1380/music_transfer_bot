# tests/conftest.py
import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv

# Добавляем корень проекта (где лежит ya2spotify.py) в PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ya2spotify import get_spotify_token  # актуальное имя

@pytest.fixture(scope="session")
def spotify_token():
    """
    Выдаёт валидный токен Spotify или скипает все тесты,
    если нет SPOTIFY_CLIENT_ID/SECRET в .env.
    """
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    cid = os.getenv("SPOTIFY_CLIENT_ID")
    csec = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        pytest.skip("SPOTIFY_CLIENT_ID/SECRET отсутствуют. Добавь их в .env для интеграционных тестов.")
    return get_spotify_token(cid, csec)