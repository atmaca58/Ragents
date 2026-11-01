"""CLI ve MCP'nin ortak kalıcı katalog görünümü."""
from pathlib import Path

from ragents.catalog import AGENT_ID_PATTERN, list_agents, load_agent, project_config
from ragents.config import ProjectConfig
from ragents.storage import TaskStateError


class ManagementCatalog:
    def __init__(self, root: Path | None, legacy: dict[str, ProjectConfig]):
        self.root = root.resolve() if root is not None else None
        self.legacy = legacy

    def contains(self, agent_id: str) -> bool:
        if not AGENT_ID_PATTERN.fullmatch(agent_id):
            raise TaskStateError("Ajan kimliği geçersiz.")
        return self.root is not None and (self.root / "agents" / agent_id).exists()

    def resolve(self, agent_id: str) -> ProjectConfig:
        if self.contains(agent_id):
            return project_config(load_agent(self.root, agent_id))
        if agent_id not in self.legacy:
            raise TaskStateError("Ajan kayıtlı değil; önce list_agents çağırın.")
        return self.legacy[agent_id]

    @staticmethod
    def payload(config: ProjectConfig) -> dict:
        return {"id": config.agent.id, "name": config.agent.name,
                "connection": config.agent.connection,
                "connections": [{"id": name, "provider": spec.provider, "model": spec.model}
                                for name, spec in config.connections.items()]}

    def list(self) -> list[dict]:
        result = {identity: self.payload(config) for identity, config in self.legacy.items()}
        if self.root is not None:
            for summary in list_agents(self.root, include_archived=True):
                if not summary.valid:
                    result[summary.id] = {"id": summary.id, "valid": False}
                    continue
                result[summary.id] = {
                    **self.payload(self.resolve(summary.id)), "status": summary.status,
                    "workspace_ready": summary.workspace_ready, "revision": summary.revision,
                }
        return list(result.values())
