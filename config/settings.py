"""
Configuración del proyecto Uniforma (Django + PostgreSQL).

Las credenciales NUNCA van en el código: se leen de variables de entorno
(ver .env.example).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    """Carga un archivo .env sencillo (CLAVE=valor) sin dependencias extra."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-cambia-esta-clave-en-produccion")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tienda",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # <--- Agrégala aquí exactamente
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tienda.context_processors.contadores",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Base de datos: PostgreSQL (UniformaDB). Para pruebas rápidas sin PostgreSQL
# se puede usar DB_ENGINE=sqlite.
# ---------------------------------------------------------------------------
if os.environ.get("DB_ENGINE", "postgres") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "uniforma_db"),
            "USER": os.environ.get("DB_USER", "uniforma"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "tienda:login"
LOGIN_REDIRECT_URL = "tienda:panel"
LOGOUT_REDIRECT_URL = "tienda:catalogo"

# Reglas de negocio (RN) del caso Uniforma
ANTICIPO_PORCENTAJE = 50   # RN-01: anticipo mínimo del 50 % para apartar
VIGENCIA_APARTADO_DIAS = 30  # Un apartado vence a los 30 días
SOLICITUD_VIGENCIA_DIAS = 7  # Una solicitud en línea sin anticipo caduca a los 7 días
AVISO_VENCIMIENTO_DIAS = 5   # Se avisa al cliente N días antes de vencer
# Configuración de archivos estáticos con WhiteNoise para producción
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
