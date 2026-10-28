
import os

REQUIRED_API_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def validate_api_keys():
    missing = [
        key for key in REQUIRED_API_KEYS
        if not os.getenv(key, "").strip()
    ]

    if missing:
        raise EnvironmentError(
            "Missing API configuration: "
            + ", ".join(missing)
        )
