import pytest
import yaml
import pathlib

from ampel.model.job.JobModel import JobModel
from ampel.dev.DevAmpelContext import DevAmpelContext
from ampel.secret.AmpelVault import AmpelVault
from ampel.secret.PotemkinSecretProvider import PotemkinSecretProvider

from ampel.argo.job import render_job
from pydantic import ValidationError


@pytest.fixture(scope="session")
def test_data():
    return pathlib.Path(__file__).parent / "test-data"


@pytest.fixture
def mock_context(test_data: pathlib.Path):
    return DevAmpelContext.load(
        config=test_data / "testing-config.yaml",
        # purge_db=True,
        vault=AmpelVault([PotemkinSecretProvider()]),
    )


@pytest.fixture(params=["ProcessLocalAlerts.yml", "TemplatedT3.yml"])
def job(request, test_data: pathlib.Path):
    with (test_data / request.param).open() as f:
        return JobModel(**yaml.safe_load(f))


def test_render(job: JobModel, mock_context: DevAmpelContext):
    assert isinstance(workflow := render_job(mock_context, job), dict)
    assert len(workflow["spec"]["templates"]) == 2
    assert (entrypoint := workflow["spec"]["templates"][-1])["name"] == "workflow"
    assert len(entrypoint["steps"]) == len(job.task)
    for step, task in zip(entrypoint["steps"], job.task):
        assert len(step) == task.multiplier


@pytest.fixture(
    params=["UnknownUnit.yml", "UnknownDrivingUnit.yml", "WrongUnitType.yml"]
)
def bad_job(request, test_data: pathlib.Path):
    with (test_data / request.param).open() as f:
        return JobModel(**yaml.safe_load(f))


def test_validate(bad_job: JobModel, mock_context: DevAmpelContext):
    with pytest.raises(ValidationError):
        render_job(mock_context, bad_job)
