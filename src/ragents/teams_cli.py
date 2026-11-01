from pathlib import Path

from ragents.profile_paths import profile_root, database_path
from ragents.teams import TeamSpec, TeamService
from ragents.storage import TaskStore, TaskStateError


def add_teams_parser(commands):
    parser = commands.add_parser("teams", help="Onaylanmış kontrollü ekipleri çalıştır ve iptal et")
    parser.add_argument("--root", type=Path)
    actions = parser.add_subparsers(dest="team_action", required=True)
    actions.add_parser("list")
    start = actions.add_parser("start")
    start.add_argument("team_id")
    start.add_argument("--key", required=True)
    for action in ("show", "cancel"):
        command = actions.add_parser(action)
        command.add_argument("run_id")


def load_team(root: Path, identity: str) -> TeamSpec:
    from ragents.setup_plans import ConnectionRef
    ConnectionRef(id=identity)
    path = root / "teams" / f"{identity}.json"
    if not path.is_file() or path.is_symlink():
        raise TaskStateError("Onaylanmış ekip tanımı bulunamadı.")
    gate = path.with_suffix(".approval")
    if gate.exists():
        import re
        request = gate.read_text(encoding="utf-8")
        if not re.fullmatch(r"[a-f0-9]{32}", request) or not (root / "approvals" / request / "operation.applied").is_file():
            raise TaskStateError("Ekip kurulumu tamamlanmadı; onaylanmış kurulumu yeniden uygulayın.")
    return TeamSpec.model_validate_json(path.read_bytes())


def list_teams(root: Path) -> list[dict]:
    directory = root / "teams"
    return [load_team(root, path.stem).model_dump(mode="json") for path in sorted(directory.glob("*.json"))]


def dispatch_teams(args):
    root = profile_root(args.root)
    if args.team_action == "list":
        return {"teams": list_teams(root)}
    service = TeamService(root, TaskStore(database_path(root)))
    if args.team_action == "start":
        return service.start(load_team(root, args.team_id), key=args.key)
    return service.cancel(args.run_id) if args.team_action == "cancel" else service.get(args.run_id)
