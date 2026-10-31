import asyncio
from pathlib import Path
import signal
import sys

from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.worker import Worker, WorkerOptions


def add_worker_parser(commands) -> None:
    parser = commands.add_parser("worker", help="Kalıcı kuyruğu sürekli işle")
    parser.add_argument("--db", type=Path, default=Path("data/ragents.db"))
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--shutdown-seconds", type=float, default=10)
    parser.add_argument("--once", action="store_true", help="Kuyruk boşalınca çık")


async def dispatch_worker(args) -> dict:
    options = WorkerOptions(concurrency=args.concurrency, poll_seconds=args.poll_seconds,
                            shutdown_seconds=args.shutdown_seconds)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}

    def request_stop(*_args):
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signum = getattr(signal, name)
            previous[signum] = signal.signal(signum, request_stop)
    try:
        print("Worker başlatılıyor; durdurmak için Ctrl+C. Görev içerikleri günlüğe yazılmaz.", file=sys.stderr)
        await Worker(TaskService(TaskStore(args.db)), options).run(stop=stop, once=args.once)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return {"worker": "stopped"}
