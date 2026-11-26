import os
from collections.abc import Iterator

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session


def database_url():
    return os.getenv("DATABASE_URL") or URL.create(
        "postgresql+psycopg",
        username=os.getenv("PGUSER", "meal"),
        password=os.getenv("PGPASSWORD", "meal_local"),
        host=os.getenv("PGHOST", "localhost"),
        database=os.getenv("PGDATABASE", "meal"),
    )


engine = create_engine(database_url(), pool_pre_ping=True)


def session() -> Iterator[Session]:
    with Session(engine) as db:
        yield db
