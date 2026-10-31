import socket
import webbrowser

import keyring
import pytest
from pydantic_ai import models

from ragents.config import load_config


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    def deny_network(*args, **kwargs):
        raise AssertionError("Test sırasında ağ erişimi yasaktır.")

    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(keyring, "get_keyring", deny_network)
    monkeypatch.setattr(webbrowser, "open", deny_network)


@pytest.fixture
def agent_spec():
    from pathlib import Path

    return load_config(Path("examples/ollama.yaml")).agent
