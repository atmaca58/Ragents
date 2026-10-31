from ragents.config import ProjectConfig, load_config
from pathlib import Path


def test_tool_selection_requires_explicit_grant_and_task_relevance():
    from ragents.mcp_client import ToolCatalog, RemoteTool

    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["mcp_servers"] = {"office": {"transport": "stdio", "command": "python", "args": ["tools.py"]}}
    data["agent"]["mcp_tools"] = [
        {"server": "office", "name": "search_mail", "keywords": ["posta", "mail"]},
        {"server": "office", "name": "calendar", "keywords": ["takvim"]},
    ]
    config = ProjectConfig.model_validate(data)
    catalog = ToolCatalog([
        RemoteTool(server="office", name="delete_all", description="posta mail", input_schema={"type": "object"}),
        RemoteTool(server="office", name="search_mail", description="Posta ara", input_schema={"type": "object"}),
        RemoteTool(server="office", name="calendar", description="Takvim", input_schema={"type": "object"}),
    ])
    selected = catalog.select(config.agent, "Son posta mesajlarını bul")
    assert [tool.name for tool in selected] == ["search_mail"]
    assert catalog.select(config.agent, "Bir şiir yaz") == []


def test_count_and_schema_budget_limit_the_selected_tools():
    from ragents.config import AgentSpec, MCPGrant, ToolSelection
    from ragents.mcp_client import ToolCatalog, RemoteTool

    tools = [RemoteTool("office", name, "Açıklama", {"type": "object"}) for name in ("one", "two")]
    agent = AgentSpec(id="test", name="Test", instructions="Kısa yanıt", connection="local",
                      mcp_tools=tuple(MCPGrant(server="office", name=tool.name, always=True) for tool in tools),
                      tool_selection=ToolSelection(max_tools=1))
    assert [tool.name for tool in ToolCatalog(tools).select(agent, "Görev")] == ["one"]
    oversized = RemoteTool("office", "one", "Açıklama", {"type": "object", "description": "x" * 1000})
    agent = agent.model_copy(update={"tool_selection": ToolSelection(max_schema_chars=256),
                                    "mcp_tools": (agent.mcp_tools[0],)})
    assert ToolCatalog([oversized]).select(agent, "Görev") == []
