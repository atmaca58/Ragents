from pathlib import Path
from typing import get_args
import sys

from ragents.config import AgentSpec, Budget, ConnectionSpec, ProjectConfig
from ragents.connections import DEFAULT_KEY_ENVS, ProviderName
from ragents.diagnostics import inspect_connection
from ragents.setup_profile import write_profile
from ragents.storage import TaskStateError
from ragents.profile_paths import profile_root


def add_setup_parser(commands) -> None:
    setup = commands.add_parser("setup", help="Sağlayıcı seç, örnek ajan ve MCP istemci ayarlarını oluştur")
    setup.add_argument("--provider", choices=get_args(ProviderName))
    setup.add_argument("--model")
    setup.add_argument("--directory", type=Path)
    setup.add_argument("--agent-id")
    setup.add_argument("--name")
    setup.add_argument("--instructions")
    setup.add_argument("--api-key-env")
    setup.add_argument("--base-url")
    setup.add_argument("--oauth-account")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--verify", action="store_true", help="Tek gerçek model isteğiyle test et; ücret/token tüketebilir")
    setup.add_argument("--login", action="store_true", help="ChatGPT tarayıcı girişini kurulum içinde aç")
    doctor = commands.add_parser("doctor", help="Yerel bağlantı kontrolü; --live ile tek gerçek model testi")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--connection")
    doctor.add_argument("--live", action="store_true", help="Sağlayıcıya tek istek gönderir; ücret/token tüketebilir")


async def dispatch_setup(args) -> dict:
    args.directory = profile_root(args.directory)
    if not args.non_interactive:
        if not sys.stdin.isatty():
            raise TaskStateError("Etkileşimli terminal gerekli; otomasyon için --non-interactive kullanın.")
        collect_settings(args)
    if not args.provider or not args.model:
        raise TaskStateError("Sağlayıcı ve model gerekli: --provider ve --model belirtin.")
    connection = ConnectionSpec(provider=args.provider, model=args.model,
                                api_key_env=args.api_key_env or DEFAULT_KEY_ENVS.get(args.provider),
                                base_url=args.base_url, oauth_account=args.oauth_account)
    endpoint = connection.base_url
    if endpoint and (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise TaskStateError("API adresi kimlik bilgisi, sorgu veya fragment içeremez; anahtar için ortam değişkeni kullanın.")
    config = ProjectConfig(schema_version=2, connections={"primary": connection}, agent=AgentSpec(
        id=args.agent_id or "assistant", name=args.name or "Örnek Asistan",
        instructions=args.instructions or "Türkçe, kısa ve açık yanıt ver. Bilmediğini belirt.", connection="primary",
        budget=Budget(request_limit=2, tool_calls_limit=0, output_tokens_limit=512),
    ))
    if args.login and args.provider != "chatgpt":
        raise TaskStateError("--login yalnız ChatGPT sağlayıcısı için kullanılabilir.")
    profile = write_profile(args.directory, config)
    report = await inspect_connection(config)
    if args.provider == "chatgpt":
        await setup_login(args, report)
        report = await inspect_connection(config)
    if not args.non_interactive and report["credentials_ready"] and not args.verify:
        args.verify = ask("Tek model isteğiyle bağlantı testi yapılsın mı? Ücret/token tüketebilir (e/h)", "h").casefold() == "e"
    if args.verify:
        report = await inspect_connection(config, live=True)
    return {**profile, "connection": report}


async def setup_login(args, report: dict) -> None:
    from ragents.auth import ChatGPTStore
    from ragents.chatgpt_login import sign_in

    if not args.login and not args.non_interactive and not report["credentials_ready"]:
        args.login = ask("ChatGPT tarayıcı girişi açılsın mı? (e/h)", "h").casefold() == "e"
    if args.login:
        await sign_in(ChatGPTStore(args.oauth_account or "default"))


def ask(label: str, default: str = "") -> str:
    print(label + (f" [{default}]" if default else "") + ": ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip() or default
    except EOFError:
        raise TaskStateError("Kurulum girdisi sona erdi; otomasyon için --non-interactive kullanın.") from None


def collect_settings(args) -> None:
    print("Sağlayıcılar: " + ", ".join(get_args(ProviderName)), file=sys.stderr)
    args.provider = args.provider or ask("Sağlayıcı")
    if args.provider not in get_args(ProviderName):
        raise TaskStateError("Desteklenmeyen sağlayıcı; listedeki kimliklerden birini seçin.")
    args.model = args.model or ask("Hesabınızdaki/yerel model kimliği")
    args.agent_id = args.agent_id or ask("Ajan kimliği", "assistant")
    args.name = args.name or ask("Ajan adı", "Örnek Asistan")
    args.instructions = args.instructions or ask("Ajan talimatı", "Türkçe, kısa ve açık yanıt ver. Bilmediğini belirt.")
    if args.provider == "ollama":
        args.base_url = args.base_url or ask("Ollama API adresi", "http://localhost:11434/v1")
    elif args.provider in DEFAULT_KEY_ENVS:
        args.api_key_env = args.api_key_env or ask("API anahtarının ortam değişkeni adı (değeri değil)",
                                                  DEFAULT_KEY_ENVS[args.provider])
    else:
        args.oauth_account = args.oauth_account or ask("R Agents ChatGPT hesap etiketi", "default")
