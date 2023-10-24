import pytest
import httpx
from pytest_mock import MockerFixture
from starlette import status

import pytest
import pytest_asyncio
import os

from ampel.argo import api

from ampel.argo.models import ArgoJobModel
from ampel.argo.settings import settings


@pytest_asyncio.fixture
async def mock_client(mock_context, mocker: MockerFixture):
    from ampel.argo import app, auth

    ctx = mocker.patch("ampel.argo.app.get_context", return_value=mock_context)
    async with httpx.AsyncClient(app=app.app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_serviceaccount(monkeypatch: pytest.MonkeyPatch):
    try:
        monkeypatch.setenv(
            "SERVICE_ACCOUNT_TOKEN",
            os.environ["ARGO_TOKEN"],
        )
        monkeypatch.setenv("ARGO_BASE_URL", os.environ["ARGO_URL"])
    except KeyError:
        raise pytest.skip("Argo integration tests require ARGO_TOKEN env var")
    monkeypatch.setenv("VERIFY_SSL", "False")
    yield
    api.KubernetesSettings.get.cache_clear()


@pytest.fixture
def mock_auth(monkeypatch: pytest.MonkeyPatch):
    from ampel.argo import app, auth

    async def mock_get_user():
        return auth.User(name="jimmyhoffa", orgs=["AmpelProject"], teams=[])

    monkeypatch.setitem(app.app.dependency_overrides, auth.get_user, mock_get_user)


@pytest.fixture
async def clear_templates(mock_serviceaccount):
    async with api.api_client() as client:
        response = await client.get("api/v1/workflow-templates/ampel")
        response.raise_for_status()
        for item in response.json()["items"] or []:
            (
                await client.delete(
                    f'api/v1/workflow-templates/{item["metadata"]["namespace"]}/{item["metadata"]["name"]}'
                )
            ).raise_for_status()


@pytest.mark.asyncio
async def test_lint(mock_client: httpx.AsyncClient, job: ArgoJobModel):
    response = await mock_client.post(
        "/jobs/lint", data=job.json(), headers={"Content-Type": "application/json"}
    )
    assert response.json()
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_lint_bad(mock_client: httpx.AsyncClient, bad_job: ArgoJobModel):
    response = await mock_client.post("/jobs/lint", json=bad_job.dict())
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.parametrize(
    "image, status",
    [
        ("ampel:latest", status.HTTP_200_OK),
        (f"{settings.container_registry}/ampel", status.HTTP_200_OK),
        ("malicio.us/ampel:vbad", status.HTTP_422_UNPROCESSABLE_ENTITY),
    ],
)
@pytest.mark.asyncio
async def test_validate_image(mock_client: httpx.AsyncClient, image: str, status: int):
    response = await mock_client.post(
        "/jobs/lint", json={"name": "foo", "task": [], "image": image}
    )
    assert response.status_code == status


@pytest.mark.asyncio
async def test_get(
    mock_client: httpx.AsyncClient, mock_auth, mock_serviceaccount, job: ArgoJobModel
):
    async with api.api_client() as client:
        response = await client.get("api/v1/workflows/ampel")
        response.raise_for_status()


@pytest.mark.asyncio
async def test_post(
    mock_client: httpx.AsyncClient,
    mock_auth,
    mock_serviceaccount,
    clear_templates,
    job: ArgoJobModel,
):

    response = await mock_client.post("jobs", json=job.dict())
    response.raise_for_status()
