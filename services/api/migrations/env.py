import os

from alembic import context
from room_api.store.schema import metadata
from sqlalchemy import create_engine

url = os.environ.get("ROOM_MIGRATE_URL") or os.environ.get(
    "ROOM_DATABASE_URL", "postgresql+psycopg://room:room-local-dev-only@127.0.0.1:54329/room"
)


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
