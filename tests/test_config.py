
import pytest
from config import validate_api_keys


def test_valid_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    validate_api_keys()


@pytest.mark.parametrize(
    "missing_key",
    ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
)
def test_missing_api_key(monkeypatch, missing_key):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    monkeypatch.delenv(missing_key)

    with pytest.raises(EnvironmentError, match=missing_key):
        validate_api_keys()
