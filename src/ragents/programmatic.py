"""Kapalı kayıtlı, model gerektirmeyen işler; keyfi komut/import kabul etmez."""
import asyncio
import json
import platform
from typing import Literal

from pydantic import Field, field_validator

from ragents.config import Spec
from ragents.contracts import RunResult, Usage
from ragents.errors import WorkspaceError
from ragents.workspace import Workspace, WorkspaceGrant, normalize_relative_path


HandlerName = Literal["runtime_health", "workspace_inventory"]


class ProgrammaticJob(Spec):
    handler: HandlerName
    path: str = Field(default=".", min_length=1, max_length=512)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value):
        try:
            return normalize_relative_path(value)
        except WorkspaceError as error:
            raise ValueError(str(error)) from None


def _runtime_health(job: ProgrammaticJob, grant: WorkspaceGrant | None) -> dict:
    return {"handler": job.handler, "python": platform.python_version(),
            "platform": platform.system(), "model_requests": 0}


def _workspace_inventory(job: ProgrammaticJob, grant: WorkspaceGrant | None) -> dict:
    if grant is None:
        raise WorkspaceError("Dosya envanteri workspace izni gerektirir.")
    workspace = Workspace(grant.root, grant.protected_paths, readable_paths=grant.readable_paths)
    return {"handler": job.handler, **workspace.list_files(job.path)}


HANDLERS = {"runtime_health": _runtime_health, "workspace_inventory": _workspace_inventory}


async def run_programmatic(job: ProgrammaticJob, agent_id: str, grant: WorkspaceGrant | None) -> RunResult:
    output = await asyncio.to_thread(HANDLERS[job.handler], job, grant)
    return RunResult(agent_id=agent_id, output=json.dumps(output, ensure_ascii=False),
                     usage=Usage(requests=0, tool_calls=0))
