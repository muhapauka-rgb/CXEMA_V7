from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import Base
from app.models import AppSettings, UsnMode


@pytest.fixture()
def db(tmp_path: Path) -> Session:
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        class_=Session,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        # Explicit settings row keeps tax mode deterministic in tests.
        session.add(AppSettings(id=1, usn_mode=UsnMode.OPERATIONAL, usn_rate_percent=6.0))
        session.commit()
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
