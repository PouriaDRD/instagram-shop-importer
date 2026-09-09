from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


TRUE_VALUES: frozenset[str] = frozenset(
    {
        "1",
        "true",
        "yes",
        "on",
    }
)

FALSE_VALUES: frozenset[str] = frozenset(
    {
        "0",
        "false",
        "no",
        "off",
    }
)


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


def _get_raw_env(
    key: str,
) -> str | None:
    """
    Return a normalized environment variable.

    Empty or whitespace-only values are treated as missing.
    """

    value = os.getenv(key)

    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    return value


def get_env_str(
    key: str,
    *,
    default: str | None = None,
    required: bool = False,
) -> str:
    """
    Read a string environment variable.
    """

    value = _get_raw_env(key)

    if value is not None:
        return value

    if required:
        raise ConfigurationError(
            f"Missing required environment variable: {key}"
        )

    if default is None:
        raise ConfigurationError(
            (
                f"Environment variable '{key}' is missing "
                "and no default value was provided."
            )
        )

    return default


def get_env_int(
    key: str,
    *,
    default: int | None = None,
    required: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Read an integer environment variable.

    Optional minimum and maximum bounds can also be enforced.
    """

    raw_value = _get_raw_env(key)

    if raw_value is None:
        if required:
            raise ConfigurationError(
                f"Missing required environment variable: {key}"
            )

        if default is None:
            raise ConfigurationError(
                (
                    f"Environment variable '{key}' is missing "
                    "and no default value was provided."
                )
            )

        value = default

    else:
        try:
            value = int(raw_value)

        except ValueError as exc:
            raise ConfigurationError(
                (
                    f"Environment variable '{key}' must be "
                    f"an integer, received: {raw_value!r}"
                )
            ) from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(
            (
                f"Environment variable '{key}' must be "
                f">= {minimum}, received: {value}"
            )
        )

    if maximum is not None and value > maximum:
        raise ConfigurationError(
            (
                f"Environment variable '{key}' must be "
                f"<= {maximum}, received: {value}"
            )
        )

    return value


def get_env_bool(
    key: str,
    *,
    default: bool | None = None,
    required: bool = False,
) -> bool:
    """
    Read a boolean environment variable.
    """

    raw_value = _get_raw_env(key)

    if raw_value is None:
        if required:
            raise ConfigurationError(
                f"Missing required environment variable: {key}"
            )

        if default is None:
            raise ConfigurationError(
                (
                    f"Environment variable '{key}' is missing "
                    "and no default value was provided."
                )
            )

        return default

    normalized = raw_value.strip().lower()

    if normalized in TRUE_VALUES:
        return True

    if normalized in FALSE_VALUES:
        return False

    raise ConfigurationError(
        (
            f"Environment variable '{key}' must be a boolean. "
            "Accepted values: "
            "true, false, 1, 0, yes, no, on, off. "
            f"Received: {raw_value!r}"
        )
    )


class Config:
    """
    Central application configuration.
    """

    DEBUG: bool = get_env_bool(
        "DEBUG",
        default=True,
    )

    SECRET_KEY: str = get_env_str(
        "SECRET_KEY",
        default="strong-dev-secret-key",
    )

    LOG_LEVEL: str = (
        get_env_str(
            "LOG_LEVEL",
            default="INFO",
        )
        .strip()
        .upper()
    )

    HOSTNAME: str = get_env_str(
        "HOSTNAME",
        default="127.0.0.1",
    )

    PORT: int = get_env_int(
        "PORT",
        default=5050,
        minimum=1,
        maximum=65535,
    )

    SQLALCHEMY_DATABASE_URI: str = get_env_str(
        "DATABASE_URL",
        default="sqlite:///instagram_importer.db",
    )

    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    PLAYWRIGHT_HEADLESS: bool = get_env_bool(
        "PLAYWRIGHT_HEADLESS",
        default=True,
    )

    PLAYWRIGHT_TIMEOUT_MS: int = get_env_int(
        "PLAYWRIGHT_TIMEOUT_MS",
        default=30_000,
        minimum=1_000,
    )

    PLAYWRIGHT_BROWSER_EXECUTABLE: str = get_env_str(
        "PLAYWRIGHT_BROWSER_EXECUTABLE",
        default="",
    )

    # ========================================================
    # Persistent local Instagram media storage
    # ========================================================

    INSTAGRAM_MEDIA_STORAGE_ENABLED: bool = get_env_bool(
        "INSTAGRAM_MEDIA_STORAGE_ENABLED",
        default=True,
    )

    INSTAGRAM_MEDIA_STORAGE_DIR: str = get_env_str(
        "INSTAGRAM_MEDIA_STORAGE_DIR",
        default="instance/media/instagram",
    )

    INSTAGRAM_MEDIA_STORAGE_TIMEOUT_SECONDS: int = get_env_int(
        "INSTAGRAM_MEDIA_STORAGE_TIMEOUT_SECONDS",
        default=30,
        minimum=1,
        maximum=300,
    )

    INSTAGRAM_MEDIA_STORAGE_MAX_BYTES: int = get_env_int(
        "INSTAGRAM_MEDIA_STORAGE_MAX_BYTES",
        default=262_144_000,
        minimum=1_048_576,
        maximum=2_147_483_647,
    )

    # ========================================================
    # Selora integration
    # ========================================================

    SELORA_API_BASE_URL: str = get_env_str(
        "SELORA_API_BASE_URL",
        default="http://127.0.0.1:8000",
    )

    SELORA_API_KEY: str = get_env_str(
        "SELORA_API_KEY",
        default="",
    )

    SELORA_API_CONNECT_TIMEOUT_SECONDS: int = get_env_int(
        "SELORA_API_CONNECT_TIMEOUT_SECONDS",
        default=5,
        minimum=1,
        maximum=60,
    )

    SELORA_API_READ_TIMEOUT_SECONDS: int = get_env_int(
        "SELORA_API_READ_TIMEOUT_SECONDS",
        default=30,
        minimum=1,
        maximum=300,
    )

    CLIENT_INSTANCE_ID_FILE: str = get_env_str(
        "CLIENT_INSTANCE_ID_FILE",
        default="instance/client_instance_id",
    )

    SELORA_WORKSPACE_HEARTBEAT_SECONDS: int = get_env_int(
        "SELORA_WORKSPACE_HEARTBEAT_SECONDS",
        default=120,
        minimum=30,
        maximum=600,
    )
