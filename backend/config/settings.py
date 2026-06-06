import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
REPO_ROOT = BASE_DIR.parent                                 # repo root (shared/, data/)
sys.path.insert(0, str(REPO_ROOT))

load_dotenv(BASE_DIR / ".env")

from shared.provider import configure_provider  # noqa: E402

LLM_PROVIDER = configure_provider()

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []

# No relational data; sqlite placeholder keeps Django happy.
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS — chat frontend origin(s)
_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _origins and _origins != "*":
    # django-cors-headers needs scheme://host entries; "*" is NOT valid here —
    # it requires CORS_ALLOW_ALL_ORIGINS instead (handled in the else branch).
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]
else:
    CORS_ALLOW_ALL_ORIGINS = True  # no credentials/cookies used, so safe

REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/hour"},
}

CHAT_MODEL = os.environ["CHAT_MODEL"]  # set by configure_provider()
