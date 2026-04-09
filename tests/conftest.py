import pytest


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    from httpx import AsyncClient

    return AsyncClient(app=app, base_url="http://test")
