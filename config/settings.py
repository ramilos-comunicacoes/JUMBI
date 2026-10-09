import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
if not DEBUG and (len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("unsafe-", "change-"))):
    raise ImproperlyConfigured("Configure DJANGO_SECRET_KEY aleatória com pelo menos 50 caracteres para produção.")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
JUMBI_LEGAL_ONLY = os.getenv("JUMBI_LEGAL_ONLY", "True").lower() == "true"
JUMBI_ENFORCE_SUBSCRIPTIONS = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.office",
    "apps.partners",
    "apps.engineering",
    "apps.agro",
    "apps.pages",
    "apps.legal",
    "apps.billing",
    "apps.performance",
    "apps.contracts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.workspace_middleware.OrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.billing.middleware.SubscriptionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.core.context_processors.organization_context",
        "apps.core.workspace_context.workspace_context",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("DJANGO_DB_ENGINE") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "djumbi"),
        "USER": os.getenv("POSTGRES_USER", "djumbi"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }}

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = Path(os.getenv("JUMBI_PRIVATE_MEDIA_ROOT", str(BASE_DIR / "private_media")))
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 18 * 1024 * 1024
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG:
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.User"
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
AUTHENTICATION_BACKENDS = ["apps.core.workspace_auth.EmailBackend"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
if not DEBUG:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "jumbi_cache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "False").lower() == "true"
