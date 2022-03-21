import pytest
import yaml
import pathlib

from ampel.model.job.JobModel import JobModel
from ampel.dev.DevAmpelContext import DevAmpelContext
from ampel.abstract.AbsProcessController import AbsProcessController

from pydantic import ValidationError



def test_render(job: JobModel, mock_context: DevAmpelContext):
    from ampel.argo.job import render_job
    assert isinstance(workflow := render_job(mock_context, job), dict)
    assert len(workflow["spec"]["templates"]) == 2
    assert (entrypoint := workflow["spec"]["templates"][-1])["name"] == "workflow"
    assert len(entrypoint["steps"]) == len(job.task)
    for step, task in zip(entrypoint["steps"], job.task):
        assert len(step) == task.multiplier


def test_validate(bad_job: JobModel, mock_context: DevAmpelContext):
    from ampel.argo.job import render_job
    with pytest.raises(ValidationError):
        render_job(mock_context, bad_job)

def test_validate_job_name(test_data: pathlib.Path):
    from ampel.argo.models import ArgoJobModel

    with (test_data / "ProcessLocalAlerts.yml").open() as f:
        ArgoJobModel(**yaml.safe_load(f))
