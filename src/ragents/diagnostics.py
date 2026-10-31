from ragents.chatgpt_login import auth_status
from ragents.auth import ChatGPTStore
from ragents.config import Budget, ProjectConfig
from ragents.providers import resolve_connection
from ragents.errors import AuthError
from ragents.storage import TaskStateError


async def inspect_connection(config: ProjectConfig, connection_id: str | None = None, *, live: bool = False) -> dict:
    selected = connection_id if connection_id is not None else config.agent.connection
    if selected not in config.connections:
        raise TaskStateError("Seçilen bağlantı tanımlı değil.")
    connection = config.connections[selected]
    report = {"connection_id": selected, "provider": connection.provider, "model": connection.model,
              "credentials_ready": False, "remote_validated": False, "model_requests": 0}
    if connection.provider == "chatgpt":
        try:
            status = await auth_status(ChatGPTStore(connection.oauth_account or "default"))
            report["credentials_ready"] = status["signed_in"] and status["plan_usage_granted"]
        except AuthError:
            pass
        report["auth_argv"] = ["auth", "login", "chatgpt", "--account", connection.oauth_account or "default"]
    else:
        try:
            resolve_connection(connection)
            report["credentials_ready"] = True
        except ValueError:
            pass
        report["api_key_env"] = connection.api_key_env
    if not report["credentials_ready"]:
        report["error_code"] = "credentials_required"
    if live and report["credentials_ready"]:
        await probe_connection(config, selected, report)
    return report


async def probe_connection(config: ProjectConfig, selected: str, report: dict) -> None:
    from ragents.application import run_task
    from ragents.task_service import failure_code

    agent = config.agent.model_copy(update={
        "instructions": "Yalnız OK yaz.", "tools": (), "mcp_tools": (),
        "budget": Budget(request_limit=1, tool_calls_limit=0, output_tokens_limit=128,
                         input_tokens_limit=1024, total_tokens_limit=1152, timeout_seconds=20),
    })
    try:
        result = await run_task(config.model_copy(update={"agent": agent}), "Bağlantı testi: OK", selected)
    except Exception as error:
        report["error_code"] = failure_code(error)
        report["model_requests"] = None  # İstek uzakta işlenmiş olabilir; bilinmeyen tüketim sıfır değildir.
        return
    report.update(remote_validated=True, model_requests=result.usage.requests, usage=result.usage.model_dump())
