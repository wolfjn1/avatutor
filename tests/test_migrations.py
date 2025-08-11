from __future__ import annotations

import os
from sqlalchemy import create_engine, inspect


def test_alembic_upgrades_apply_tables(tmp_path) -> None:  # type: ignore[no-any-unimported]
    # Use SQLite in-memory/file DB to validate migration application
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Import after setting DATABASE_URL so init_db picks it up
    from apps.api.db import init_db

    init_db()

    engine = create_engine(os.environ["DATABASE_URL"])  # type: ignore[no-any-unimported]
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    # Tables created by initial migration
    for name in {"feature_flags", "events", "approvals", "decisions", "dlq"}:
        assert name in tables


