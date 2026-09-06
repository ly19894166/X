"""Migration 1：Core 表、唯一键、外键及不可变触发器。"""
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, MetaData, String, Table, Text

metadata = MetaData()
batches = Table("batches", metadata,
    Column("batch_id", String, primary_key=True),
    Column("fingerprint", String, nullable=False))
receipts = Table("commit_receipts", metadata,
    Column("batch_id", ForeignKey("batches.batch_id"), primary_key=True),
    Column("recorded_at", String, nullable=False),
    Column("contract_checked_at", String, nullable=False),
    Column("recovered", Integer, nullable=False))
publications = Table("publication_fences", metadata,
    Column("batch_id", ForeignKey("commit_receipts.batch_id"), primary_key=True),
    Column("available_at", String, nullable=False),
    Column("recovered", Integer, nullable=False))
records = Table("versions", metadata,
    Column("object_id", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("kind", String, nullable=False),
    Column("batch_id", ForeignKey("batches.batch_id"), nullable=False),
    Column("payload", Text, nullable=False),
    Column("payload_hash", String, nullable=False))
raw_archive = Table("raw_archive", metadata,
    Column("raw_id", String, primary_key=True),
    Column("batch_id", ForeignKey("batches.batch_id"), nullable=False),
    Column("source_id", String, nullable=False),
    Column("locator", Text, nullable=False),
    Column("content_version", String, nullable=False),
    Column("first_seen_at", String, nullable=False),
    Column("collected_at", String, nullable=False),
    Column("raw_bytes", LargeBinary, nullable=False),
    Column("raw_hash", String, nullable=False),
    Column("normalized_hash", String, nullable=False))


def migrate(engine):
    with engine.begin() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar_one()
        if version not in (0, 1):
            raise ValueError("MIGRATION_HOLD：数据库版本高于本程序")
        if version == 0 and conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").first():
            raise ValueError("MIGRATION_HOLD：拒绝初始化已有未知业务表的数据库")
        metadata.create_all(conn)
        for table in metadata.sorted_tables:
            for operation in ("UPDATE", "DELETE"):
                conn.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table.name}_{operation.lower()} "
                    f"BEFORE {operation} ON {table.name} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
        conn.exec_driver_sql("PRAGMA user_version=1")
