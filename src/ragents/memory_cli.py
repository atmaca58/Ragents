from pathlib import Path

from ragents.memory import MemoryService
from ragents.profile_paths import database_path
from ragents.storage import TaskStore


def add_memory_parser(commands):
    parser = commands.add_parser("memory", help="Kaynaklı proje kayıtları; onay yalnız yerel kullanıcı akışındadır")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--db", type=Path)
    actions = parser.add_subparsers(dest="memory_action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--agent", required=True)
    propose = actions.add_parser("propose", help="Doğrulanmış çalışmadan onaysız aday kaydı oluştur")
    propose.add_argument("--agent", required=True)
    propose.add_argument("--source-run", required=True)
    propose.add_argument("--keyword", action="append", required=True)
    propose.add_argument("--text", required=True)
    for name in ("show", "approve", "revise", "archive"):
        action = actions.add_parser(name)
        action.add_argument("entry_id")
        if name != "show":
            action.add_argument("--revision", type=int, required=True)
        if name == "revise":
            action.add_argument("--text", required=True)


def dispatch_memory(args):
    service = MemoryService(TaskStore(database_path(args.root, args.db)))
    action = args.memory_action
    if action == "list":
        return {"memory": [entry.model_dump() for entry in service.list(args.agent)]}
    if action == "propose":
        result = service.propose(args.agent, args.text, args.source_run, tuple(args.keyword))
    elif action == "show":
        result = service.get(args.entry_id)
    elif action == "revise":
        result = service.revise(args.entry_id, args.revision, args.text)
    elif action == "approve":
        result = service.approve(args.entry_id, args.revision)
    else:
        result = service.archive(args.entry_id, args.revision)
    return {"memory": result.model_dump()}
