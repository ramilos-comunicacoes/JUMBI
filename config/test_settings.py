"""Explicit test-only settings; production uses config.settings."""
from .settings import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

if os.getenv("JUMBI_TEST_DB_NAME"):  # noqa: F405
    test_name = os.environ["JUMBI_TEST_DB_NAME"]  # noqa: F405
    if not test_name.startswith("test_jumbi_"):
        raise ValueError("Use um banco exclusivo de testes com prefixo test_jumbi_.")
    DATABASES["default"]["NAME"] = test_name  # noqa: F405
    DATABASES["default"].setdefault("TEST", {})["NAME"] = test_name  # noqa: F405
