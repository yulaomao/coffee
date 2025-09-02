from __future__ import annotations
import os
import pytest
from app import create_app
from app.extensions import db


@pytest.fixture(scope="session")
def app():
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_db.sqlite")
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()
