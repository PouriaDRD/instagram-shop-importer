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

    Args:
        key:
            Environment variable name.

        default:
            Value returned when the variable is missing.

        required:
            When True, missing or empty values raise
            ConfigurationError.

    Returns:
        A validated string value.

    Raises:
        ConfigurationError:
            If the value is required but missing, or if neither
            a value nor a default exists.
    """

    value = _get_raw_env(key)

    if value is not None:
        return value

    if required:
        raise ConfigurationError(f"Missing required environment variable: {key}")

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
            raise ConfigurationError(f"Missing required environment variable: {key}")

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

    Accepted true values:
        1, true, yes, on

    Accepted false values:
        0, false, no, off
    """

    raw_value = _get_raw_env(key)

    if raw_value is None:
        if required:
            raise ConfigurationError(f"Missing required environment variable: {key}")

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

    All configuration is loaded once at application startup and
    exposed through explicitly typed class attributes.
    """

    # ========================================================
    # Application
    # ========================================================

    DEBUG: bool = get_env_bool(
        "DEBUG",
        default=True,
    )

    SECRET_KEY: str = get_env_str(
        "SECRET_KEY",
        default="strong-dev-secret-key",
    )

    # ========================================================
    # Logging
    # ========================================================

    LOG_LEVEL: str = (
        get_env_str(
            "LOG_LEVEL",
            default="INFO",
        )
        .strip()
        .upper()
    )

    # ========================================================
    # Web server
    # ========================================================

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

    # ========================================================
    # Database
    # ========================================================

    SQLALCHEMY_DATABASE_URI: str = get_env_str(
        "DATABASE_URL",
        default="sqlite:///instagram_importer.db",
    )

    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # ========================================================
    # Playwright
    # ========================================================

    PLAYWRIGHT_HEADLESS: bool = get_env_bool(
        "PLAYWRIGHT_HEADLESS",
        default=True,
    )

    PLAYWRIGHT_TIMEOUT_MS: int = get_env_int(
        "PLAYWRIGHT_TIMEOUT_MS",
        default=30_000,
        minimum=1_000,
    )

    # ========================================================
    # Selora integration
    # ========================================================

    SELORA_API_BASE_URL: str = get_env_str(
        "SELORA_API_BASE_URL",
        default="http://127.0.0.1:8000",
    )

    SELORA_API_TOKEN: str = get_env_str(
        "SELORA_API_TOKEN",
        default="",
    )
