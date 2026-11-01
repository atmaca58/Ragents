from contextlib import closing
from pathlib import Path
import sqlite3

from ragents.backups import backup_database, restore_database
from ragents.profile_paths import database_path, profile_root


def add_profile_parser(commands):
    parser = commands.add_parser("profile", help="Kullanıcı profili, DB yedeği ve yeni köke geri yükleme")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--db", type=Path)
    actions = parser.add_subparsers(dest="profile_action", required=True)
    actions.add_parser("status")
    backup = actions.add_parser("backup", help="SQLite WAL dahil tutarlı görev DB yedeği")
    backup.add_argument("--output", type=Path, required=True)
    restore = actions.add_parser("restore", help="Yedeği yalnız yeni bir veritabanına aç")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    export = actions.add_parser("export", help="Kimlik bilgileri olmadan taşınabilir profil paketi oluştur")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--include-history", action="store_true")
    export.add_argument("--include-workspaces", action="store_true")
    export.add_argument("--include-artifacts", action="store_true")
    for action in ("preview-import", "import"):
        command = actions.add_parser(action)
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--target", type=Path, required=True)
        command.add_argument("--mapping", type=Path, required=True, help="Ajan kimliği → yeni mutlak workspace yolu JSON dosyası")
        if action == "import":
            command.add_argument("--operation-hash", required=True)


def dispatch_profile(args):
    from ragents.profile_bundle import export_profile, preview_import, import_profile
    import json
    if args.profile_action == "export":
        path = export_profile(profile_root(args.root), args.output, include_history=args.include_history,
                              include_workspaces=args.include_workspaces, include_artifacts=args.include_artifacts)
        return {"bundle": str(path), "credentials_excluded": True}
    if args.profile_action in ("preview-import", "import"):
        mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
        if args.profile_action == "preview-import":
            return preview_import(args.bundle, args.target, mapping)
        return import_profile(args.bundle, args.target, mapping, args.operation_hash)
    database = database_path(args.root, args.db)
    if args.profile_action == "backup":
        return {"backup": str(backup_database(database, args.output)), "excludes_credential_vault": True,
                "includes": "Görev DB'si; ajan dosyaları ve workspace bu yedeğe dahil değil."}
    if args.profile_action == "restore":
        return {"restored_database": str(restore_database(args.backup, args.output))}
    result = {"profile": str(profile_root(args.root)), "database": str(database),
              "database_exists": database.is_file(), "schema": None, "integrity": None}
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            result.update(schema=db.execute("PRAGMA user_version").fetchone()[0],
                          integrity=db.execute("PRAGMA quick_check").fetchone()[0])
    return result
