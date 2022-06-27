import pytest
import pathlib
import yaml

from ampel.model.job.JobModel import JobModel

from ampel.dev.DevAmpelContext import DevAmpelContext
from ampel.secret.AmpelVault import AmpelVault
from ampel.secret.PotemkinSecretProvider import PotemkinSecretProvider


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


@pytest.fixture(
    params=[
        "ProcessLocalAlerts.yml",
        "TemplatedT3.yml",
        "ParameterPassing.yml",
        "InputArtifacts.yml",
        "ExpandedTasks.yml",
    ]
)
def job(request, test_data: pathlib.Path):
    with (test_data / request.param).open() as f:
        return JobModel(**yaml.safe_load(f))


@pytest.fixture(
    params=["UnknownUnit.yml", "UnknownDrivingUnit.yml", "WrongUnitType.yml"]
)
def bad_job(request, test_data: pathlib.Path):
    with (test_data / request.param).open() as f:
        return JobModel(**yaml.safe_load(f))
