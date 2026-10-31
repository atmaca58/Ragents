import argparse
from pathlib import Path

from ragents.config import load_config
from ragents.storage import TaskStateError, TaskStore
from ragents.task_service import TaskService


def add_task_parser(commands) -> None:
    parser = commands.add_parser("tasks", help="Kalıcı görev ve çalışma kayıtları")
    parser.add_argument("--db", type=Path, default=Path("data/ragents.db"), help="V2 SQLite dosyası")
    actions = parser.add_subparsers(dest="task_action", required=True)
    add = actions.add_parser("add", help="Görevi kaydet; model çağrısı yapma")
    add.add_argument("--config", type=Path, required=True)
    add.add_argument("--connection")
    add.add_argument("--key", help="Aynı görevin tekrar eklenmesini önleyen anahtar")
    add.add_argument("prompt")
    show = actions.add_parser("show", help="Görev ve çalışma metadatasını göster")
    show.add_argument("task_id")
    run = actions.add_parser("run", help="Sıradaki görevi çalıştır; tamamlanmışsa kayıtlı sonucu al")
    run.add_argument("task_id")
    listing = actions.add_parser("list", help="Son görevleri listele")
    listing.add_argument("--limit", type=int, default=50)
    result = actions.add_parser("result", help="Bir çalışmanın kayıtlı sonucunu al")
    result.add_argument("run_id")
    actions.add_parser("recover", help="Süreci kalmamış aktif işleri kesilmiş olarak işaretle")
    retry = actions.add_parser("retry", help="Başarısız/kesilmiş işi sıraya al; model çağrısı yapma")
    retry.add_argument("task_id")
    cancel = actions.add_parser("cancel", help="Bekleyen görevi iptal et veya çalışan göreve iptal isteği gönder")
    cancel.add_argument("task_id")


async def dispatch_tasks(args: argparse.Namespace) -> dict:
    store = TaskStore(args.db)
    if args.task_action == "add":
        task = store.enqueue(load_config(args.config), args.prompt, args.connection, idempotency_key=args.key)
        return {"task": task.model_dump()}
    if args.task_action == "list":
        return {"tasks": [task.model_dump() for task in store.list(limit=args.limit)]}
    if args.task_action == "recover":
        return {"recovered": TaskService(store).recover()}
    if args.task_action == "retry":
        return {"task": store.retry(args.task_id).model_dump()}
    if args.task_action == "cancel":
        return {"task": store.request_cancel(args.task_id).model_dump()}
    if args.task_action == "run":
        return await execute_saved(store, args.task_id)
    if args.task_action == "result":
        result = store.result(args.run_id)
        if result is None:
            raise TaskStateError("Bu çalışma için kayıtlı sonuç yok.")
        return {"run_id": args.run_id, "result": result.model_dump()}
    return {"task": store.get(args.task_id).model_dump(),
            "runs": [run.model_dump() for run in store.runs(args.task_id)]}


async def execute_saved(store: TaskStore, task_id: str) -> dict:
    cached = store.get(task_id).status == "succeeded"
    if cached:
        run = store.runs(task_id)[-1]
    else:
        run = await TaskService(store).execute(task_id)
    result = store.result(run.id)
    if result is None:
        raise TaskStateError("Çalışmanın kayıtlı sonucu bulunamadı.")
    return {"simulation": False, "task_id": task_id, "run_id": run.id,
            "cached": cached, "result": result.model_dump()}
