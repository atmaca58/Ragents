from datetime import datetime
from pathlib import Path

from ragents.profile_paths import database_path
from ragents.schedules import ScheduleService, ScheduleTiming
from ragents.storage import TaskStore


def add_schedule_parser(commands):
    parser = commands.add_parser("schedules", help="Kalıcı tek seferlik ve cron görev takvimi")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--db", type=Path)
    actions = parser.add_subparsers(dest="schedule_action", required=True)
    create = actions.add_parser("add", help="Devre dışı görevden zamanlı iş oluştur")
    create.add_argument("--task", required=True)
    timing = create.add_mutually_exclusive_group(required=True)
    timing.add_argument("--cron")
    timing.add_argument("--at", type=datetime.fromisoformat)
    create.add_argument("--timezone", default="Europe/Istanbul")
    create.add_argument("--no-catch-up", action="store_true")
    actions.add_parser("list")
    for name in ("show", "enable", "disable"):
        action = actions.add_parser(name)
        action.add_argument("schedule_id")
        if name != "show":
            action.add_argument("--revision", type=int, required=True)


def dispatch_schedules(args):
    service = ScheduleService(TaskStore(database_path(args.root, args.db)))
    if args.schedule_action == "list":
        return {"schedules": [item.model_dump(mode="json") for item in service.list()]}
    if args.schedule_action == "add":
        result = service.create(args.task, ScheduleTiming(
            cron=args.cron, at=args.at, timezone=args.timezone, catch_up=not args.no_catch_up))
    elif args.schedule_action == "show":
        result = service.get(args.schedule_id)
    else:
        result = service.set_enabled(args.schedule_id, args.schedule_action == "enable", args.revision)
    return {"schedule": result.model_dump(mode="json")}
