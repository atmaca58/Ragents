from typing import Literal

ProviderName = Literal["ollama", "openrouter", "opencode_go", "opencode_zen", "chatgpt"]
WireAPI = Literal["chat_completions", "responses"]

DEFAULT_KEY_ENVS: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "opencode_go": "OPENCODE_GO_API_KEY",
    "opencode_zen": "OPENCODE_ZEN_API_KEY",
}

FIXED_ENDPOINTS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "opencode_go": "https://opencode.ai/inference/go/openai/v1",
    "opencode_zen": "https://opencode.ai/inference/openai/v1",
    "chatgpt": "https://api.openai.com/v1",
}
