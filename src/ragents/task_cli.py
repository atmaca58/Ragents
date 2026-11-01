import argparse
from pathlib import Path

from pydantic import ValidationError
import yaml

from ragents.catalog import enqueue_agent_task
from ragents.config import load_config
from ragents.storage import UNSET, TaskStateError, TaskStore
from ragents.task_markdown import export_markdown, import_markdown
from ragents.task_service import TaskService
from ragents.verification import VerificationPlan
from ragents.profile_paths import profile_root, database_path
from ragents.programmatic import ProgrammaticJob, HandlerName
from typing import get_args


MAX_VERIFICATION_PLAN_BYTES = 65_536


def add_task_parser(commands) -> None:
    parser = commands.add_parser("tasks", help="Kalıcı görev ve çalışma kayıtları")
    parser.add_argument("--db", type=Path, default=None,
                        help="SQLite dosyası; verilmezse --root altında data/ragents.db")
    parser.add_argument("--root", type=Path, default=None,
                        help="Ajan profillerinin kök dizini; veritabanı varsayılanını belirler")
    actions = parser.add_subparsers(dest="task_action", required=True)
    add = actions.add_parser("add", help="Görevi kaydet; model çağrısı yapma")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--agent", help="Kalıcı ajan kataloğundaki kimlik")
    add.add_argument("--connection")
    add.add_argument("--skill", action="append", default=[],
                     help="Görev için seçilecek izinli skill; birden çok kez kullanılabilir")
    add.add_argument("--writable-path", action="append", default=None,
                     help="Bu görev için yazılabilir göreli dizin; profil varsayılanını değiştirir")
    add.add_argument("--allowed-command", action="append", default=None,
                     help="Bu görev için izinli çalıştırılabilir adı; profil varsayılanını değiştirir")
    add.add_argument("--allow-network", action=argparse.BooleanOptionalAction, default=None,
                     help="Bu görevde sandbox komutlarına ağ izni ver/kaldır")
    add.add_argument("--allow-publish", action=argparse.BooleanOptionalAction, default=None,
                     help="Bu görevde push/yayın komutlarına izin ver/kaldır")
    add.add_argument("--verify-plan", type=Path,
                     help="Görevle birlikte dondurulacak YAML/JSON doğrulama planı")
    add.add_argument("--title", help="Görev başlığı; verilmezse görev metninin ilk satırı")
    add.add_argument("--description", default="", help="Görevin kısa açıklaması")
    add.add_argument("--priority", type=int, default=0,
                     help="Kuyruk önceliği; büyük değer önce çalışır (-1000..1000)")
    add.add_argument("--depends-on", action="append", default=[],
                     help="Bu görevden önce tamamlanması gereken görev kimliği; birden çok kez")
    add.add_argument("--disabled", action="store_true",
                     help="Görevi devre dışı kaydet; etkinleştirilene kadar çalışmaz")
    add.add_argument("--key", help="Aynı görevin tekrar eklenmesini önleyen anahtar")
    add.add_argument("--handler", choices=get_args(HandlerName), help="Model yerine kayıtlı programatik iş")
    add.add_argument("--handler-path", default=".", help="Dosya envanteri için göreli dizin")
    add.add_argument("prompt")
    show = actions.add_parser("show", help="Görev ve çalışma metadatasını göster")
    show.add_argument("task_id")
    edit = actions.add_parser("edit", help="Sıradaki veya başarısız görevin tanımını düzenle")
    edit.add_argument("task_id")
    edit.add_argument("--title")
    edit.add_argument("--description")
    edit.add_argument("--priority", type=int, default=None)
    edit.add_argument("--enable", action=argparse.BooleanOptionalAction, default=None,
                      help="Görevi etkinleştir/devre dışı bırak")
    edit.add_argument("--depends-on", action="append", default=None,
                      help="Bağımlılık listesini bu kimliklerle değiştir; birden çok kez")
    edit.add_argument("--clear-dependencies", action="store_true",
                      help="Tüm bağımlılıkları kaldır")
    edit.add_argument("--prompt", help="Görev metnini değiştir")
    edit.add_argument("--verify-plan", type=Path,
                      help="Doğrulama planını bu dosyayla değiştir")
    edit.add_argument("--clear-verification", action="store_true",
                      help="Doğrulama planını kaldır")
    run = actions.add_parser("run", help="Sıradaki görevi çalıştır; tamamlanmışsa kayıtlı sonucu al")
    run.add_argument("task_id")
    listing = actions.add_parser("list", help="Son görevleri listele")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--status", choices=(
        "queued", "running", "succeeded", "failed", "cancelled", "interrupted",
    ))
    archive_filter = listing.add_mutually_exclusive_group()
    archive_filter.add_argument("--include-archived", action="store_true",
                                help="Arşivlenmiş görevleri de göster")
    archive_filter.add_argument("--archived-only", action="store_true",
                                help="Yalnız arşivlenmiş görevleri göster")
    result = actions.add_parser("result", help="Bir çalışmanın kayıtlı sonucunu al")
    result.add_argument("run_id")
    actions.add_parser("recover", help="Süreci kalmamış aktif işleri kesilmiş olarak işaretle")
    retry = actions.add_parser("retry", help="Başarısız/kesilmiş işi sıraya al; model çağrısı yapma")
    retry.add_argument("task_id")
    cancel = actions.add_parser("cancel", help="Bekleyen görevi iptal et veya çalışan göreve iptal isteği gönder")
    cancel.add_argument("task_id")
    archive = actions.add_parser("archive", help="Tamamlanmış görevi arşivle")
    archive.add_argument("task_id")
    restore = actions.add_parser("restore", help="Arşivlenmiş görevi geri yükle")
    restore.add_argument("task_id")
    revisions = actions.add_parser("revisions", help="Görevin tanım revizyonlarını göster")
    revisions.add_argument("task_id")
    export = actions.add_parser("export", help="Görevleri Markdown görünümüne aktar")
    export.add_argument("--output", type=Path,
                        help="Yazılacak dosya; verilmezse standart çıktı")
    export.add_argument("--limit", type=int, default=1000)
    import_parser = actions.add_parser("import", help="Markdown görev görünümünden yeni görevler ekle")
    import_parser.add_argument("--file", type=Path, required=True)


def resolve_root(args: argparse.Namespace) -> Path | None:
    return profile_root(getattr(args, "root", None))


def resolve_database(args: argparse.Namespace) -> Path:
    return database_path(getattr(args, "root", None), getattr(args, "db", None))


def load_verification_plan(path: Path) -> VerificationPlan:
    try:
        if path.stat().st_size > MAX_VERIFICATION_PLAN_BYTES:
            raise TaskStateError("Doğrulama planı çok büyük.")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        raise TaskStateError("Doğrulama planı okunamadı.") from None
    except yaml.YAMLError:
        raise TaskStateError("Doğrulama planı geçerli YAML/JSON değil.") from None
    if not isinstance(raw, dict):
        raise TaskStateError("Doğrulama planı checks listesi içeren bir nesne olmalıdır.")
    try:
        return VerificationPlan.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        message = str(first.get("msg", "geçersiz plan"))
        raise TaskStateError(f"Doğrulama planı geçersiz: {message}") from None


async def dispatch_tasks(args: argparse.Namespace) -> dict:
    permission_flags = (
        args.task_action == "add" and args.agent is None and any((
            args.writable_path is not None, args.allowed_command is not None,
            args.allow_network is not None, args.allow_publish is not None,
        ))
    )
    if permission_flags:
        raise TaskStateError(
            "--writable-path/--allowed-command/--allow-network/--allow-publish yalnız --agent ile kullanılabilir."
        )
    if args.task_action == "add" and args.agent is None and args.skill:
        raise TaskStateError("--skill yalnız --agent ile kullanılabilir.")
    store = TaskStore(resolve_database(args))
    if args.task_action == "add":
        verification = (
            load_verification_plan(args.verify_plan) if args.verify_plan is not None else None
        )
        if verification is not None and verification.requires_workspace and args.agent is None:
            raise TaskStateError(
                "Dosya/komut doğrulaması için --agent ile workspace tanımlı görev kullanın."
            )
        metadata = {
            "title": args.title, "description": args.description,
            "priority": args.priority, "enabled": not args.disabled,
            "dependencies": tuple(args.depends_on),
            "programmatic": ProgrammaticJob(handler=args.handler, path=args.handler_path) if args.handler else None,
        }
        if args.agent is not None:
            root = resolve_root(args)
            if root is None:
                raise TaskStateError("Ajan profil kökü belirlenemedi.")
            task = enqueue_agent_task(
                store, root, args.agent, args.prompt, args.connection,
                skills=tuple(args.skill), idempotency_key=args.key,
                writable_paths=(tuple(args.writable_path)
                                if args.writable_path is not None else None),
                commands=tuple(args.allowed_command) if args.allowed_command is not None else None,
                allow_network=args.allow_network, allow_publish=args.allow_publish,
                verification=verification, **metadata,
            )
        else:
            task = store.enqueue(
                load_config(args.config), args.prompt, args.connection,
                idempotency_key=args.key, verification=verification, **metadata,
            )
        return {"task": task.model_dump()}
    if args.task_action == "edit":
        if args.depends_on is not None and args.clear_dependencies:
            raise TaskStateError("--depends-on ve --clear-dependencies birlikte kullanılamaz.")
        if args.verify_plan is not None and args.clear_verification:
            raise TaskStateError("--verify-plan ve --clear-verification birlikte kullanılamaz.")
        verification: VerificationPlan | None | object = UNSET
        if args.verify_plan is not None:
            verification = load_verification_plan(args.verify_plan)
        elif args.clear_verification:
            verification = None
        dependencies: tuple[str, ...] | None = None
        if args.clear_dependencies:
            dependencies = ()
        elif args.depends_on is not None:
            dependencies = tuple(args.depends_on)
        task = store.edit(
            args.task_id, title=args.title, description=args.description,
            priority=args.priority, enabled=args.enable,
            dependencies=dependencies, prompt=args.prompt,
            verification=verification,
        )
        return {"task": task.model_dump()}
    if args.task_action == "list":
        return {"tasks": [task.model_dump() for task in store.list(
            status=args.status, limit=args.limit,
            include_archived=args.include_archived, archived_only=args.archived_only,
        )]}
    if args.task_action == "recover":
        return {"recovered": TaskService(store).recover()}
    if args.task_action == "retry":
        return {"task": store.retry(args.task_id).model_dump()}
    if args.task_action == "cancel":
        return {"task": store.request_cancel(args.task_id).model_dump()}
    if args.task_action == "archive":
        return {"task": store.archive(args.task_id).model_dump()}
    if args.task_action == "restore":
        return {"task": store.restore(args.task_id).model_dump()}
    if args.task_action == "revisions":
        return {"revisions": [
            revision.model_dump(mode="json") for revision in store.revisions(args.task_id)
        ]}
    if args.task_action == "export":
        markdown = export_markdown(store, limit=args.limit)
        if args.output is not None:
            try:
                args.output.write_text(markdown, encoding="utf-8")
            except OSError:
                raise TaskStateError("Markdown çıktısı yazılamadı.") from None
            return {"output": str(args.output), "bytes": len(markdown.encode("utf-8"))}
        return {"markdown": markdown}
    if args.task_action == "import":
        root = resolve_root(args)
        try:
            markdown = args.file.read_text(encoding="utf-8")
        except OSError:
            raise TaskStateError("Markdown görev dosyası okunamadı.") from None
        tasks = import_markdown(store, root, markdown)
        return {"tasks": [task.model_dump() for task in tasks]}
    if args.task_action == "run":
        return await execute_saved(store, args.task_id)
    if args.task_action == "result":
        result = store.result(args.run_id)
        if result is None:
            raise TaskStateError("Bu çalışma için kayıtlı sonuç yok.")
        verification = store.verification(args.run_id)
        return {
            "run_id": args.run_id, "result": result.model_dump(),
            "verification": verification.model_dump() if verification else None,
        }
    definition = store.definition(args.task_id)
    task = store.get(args.task_id)
    blocked_by = store.blocked_by(args.task_id)
    return {"task": task.model_dump(),
            "runs": [run.model_dump() for run in store.runs(args.task_id)],
            "dependencies": list(store.dependencies(args.task_id)),
            "blocked_by": list(blocked_by),
            "ready": not blocked_by,
            "revision_history": [
                {"revision": revision.revision, "title": revision.title,
                 "created_at": revision.created_at, "reason": revision.reason}
                for revision in store.revisions(args.task_id)
            ],
            "instruction": definition.instruction.model_dump() if definition.instruction else None,
            "workspace": (
                definition.workspace.model_dump(mode="json") if definition.workspace else None
            ),
            "verification_plan": (
                definition.verification.model_dump(mode="json")
                if definition.verification else None
            ),
            "programmatic": definition.programmatic.model_dump() if definition.programmatic else None,
            "verifications": [
                record.model_dump() for record in store.verifications(args.task_id)
            ],
            "artifacts": [artifact.model_dump() for artifact in store.artifacts(args.task_id)]}


async def execute_saved(store: TaskStore, task_id: str) -> dict:
    snapshot = store.get(task_id)
    if snapshot.archived_at is not None:
        raise TaskStateError("Arşivlenmiş görev çalıştırılamaz; önce geri yükleyin.")
    cached = snapshot.status == "succeeded"
    if cached:
        run = store.runs(task_id)[-1]
    else:
        run = await TaskService(store).execute(task_id)
    result = store.result(run.id)
    if result is None:
        raise TaskStateError("Çalışmanın kayıtlı sonucu bulunamadı.")
    verification = store.verification(run.id)
    return {"simulation": False, "task_id": task_id, "run_id": run.id,
            "status": run.status, "error_code": run.error_code,
            "cached": cached, "result": result.model_dump(),
            "verification": verification.model_dump() if verification else None}
