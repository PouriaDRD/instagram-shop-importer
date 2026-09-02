import os
from typing import Optional, Type, TypeVar
from dotenv import load_dotenv

# Load environment variables from a .env file into os.environ
load_dotenv()

# Define a generic type variable restricted to supported casting types
T = TypeVar("T", str, int, bool)


def get_env(
    key: str,
    default: Optional[T] = None,
    cast_to: Type[T] = str,
    required: bool = False,
) -> T:
    """Retrieve an environment variable in a type-safe manner.

    Fetches a variable from the environment, performs type casting, and handles
    validation for required configuration values.

    Args:
        key: The name of the environment variable to retrieve.
        default: The default value to return if the environment variable is not
          set and required is False. Defaults to None.
        cast_to: The target primitive type (str, int, bool) to cast the value
          to. Defaults to str.
        required: If True, raises a ValueError when the variable is missing or
          empty. Defaults to False.

    Returns:
        The environment variable value cast to the specified type `T`, or the
        provided default value.

    Raises:
        ValueError: If `required` is True and the key is missing or empty.
        TypeError: If `cast_to` is `int` and the value cannot be converted to an
          integer.

    Example:
        >>> get_env("DEBUG", default=True, cast_to=bool)
        True
        >>> get_env("API_KEY", required=True)
        'secret_token_123'
    """
    value = os.getenv(key)

    # Validate presence and non-emptiness for required variables
    if required and (value is None or value.strip() == ""):
        raise ValueError(
            f"Configuration Error: Missing or empty required environment variable '{key}'."
        )

    # Return default value if the variable is not set and not required
    if value is None:
        return default  # type: ignore[return-value]

    # Perform type casting
    if cast_to == bool:
        # Evaluate truthy string values commonly used in .env configurations
        return value.lower() in ("true", "1", "on", "yes")  # type: ignore[return-value]

    elif cast_to == int:
        try:
            return int(value)  # type: ignore[return-value]
        except ValueError:
            raise TypeError(
                f"Type Error: Environment variable '{key}' must be a valid integer."
            )

    elif cast_to == str:
        try:
            return str(value)  # type: ignore[return-value]
        except ValueError:
            raise TypeError(
                f"Type Error: Environment variable '{key}' must be a valid string."
            )

    return value  # type: ignore[return-value]


class Config:
    """Application configuration container.

    Loads and validates application settings from environment variables with
    strict typing and default fallback values.
    """

    # --- Optional Settings (With default values) ---
    DEBUG: bool = get_env(
        "DEBUG",
        default=True,
        cast_to=bool,
    )
    SECRET_KEY: str = get_env(
        "SECRET_KEY",
        default="strong-dev-secret-key",
        cast_to=str,
    )
    PORT: int = get_env(
        "PORT",
        default=5050,
        cast_to=int,
    )
    HOSTNAME: str = get_env(
        "HOSTNAME",
        default="127.0.0.1",
        cast_to=str,
    )

    # Database Settings
    SQLALCHEMY_DATABASE_URI: str = get_env(
        "DATABASE_URL",
        default="sqlite:///instagram_importer.db",
        cast_to=str,
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Playwright Automation Settings
    PLAYWRIGHT_HEADLESS: bool = get_env(
        "PLAYWRIGHT_HEADLESS",
        default=True,
        cast_to=bool,
    )
    PLAYWRIGHT_TIMEOUT_MS: int = get_env(
        "PLAYWRIGHT_TIMEOUT_MS",
        default=30000,
        cast_to=int,
    )

    # External API Integration Settings
    SELORA_API_BASE_URL: str = get_env(
        "SELORA_API_BASE_URL",
        default="http://127.0.0.1:8000",
        cast_to=str,
    )

    # --- Required Settings (Raises ValueError if missing or empty) ---
    SELORA_API_TOKEN: str = get_env(
        "SELORA_API_TOKEN",
        required=True,
        cast_to=str,
    )
