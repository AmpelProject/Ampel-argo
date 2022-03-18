from ampel.model.job.JobModel import JobModel
import pytest
import httpx
from pytest_mock import MockerFixture
from starlette import status

from ampel.argo import app


@pytest.fixture
async def mock_client(mock_context, mocker: MockerFixture):
    ctx = mocker.patch("ampel.argo.app.get_context", return_value=mock_context)
    async with httpx.AsyncClient(app=app.app, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_lint(mock_client: httpx.AsyncClient, job: JobModel):
    response = await mock_client.post("/jobs/lint", json=job.dict())
    import yaml
    print(yaml.dump(response.json()))
    assert response.json()
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_lint_bad(mock_client: httpx.AsyncClient, bad_job: JobModel):
    response = await mock_client.post("/jobs/lint", json=bad_job.dict())
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
