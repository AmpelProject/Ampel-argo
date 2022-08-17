import pytest
import yaml
import pathlib
import subprocess
import re

from ampel.model.job.JobModel import JobModel
from ampel.model.job.utils import transform_expressions
from ampel.dev.DevAmpelContext import DevAmpelContext

from pydantic import ValidationError


def test_render(job: JobModel, mock_context: DevAmpelContext):
    from ampel.argo.job import render_job

    assert isinstance(workflow := render_job(mock_context, job), dict)
    assert len(workflow["spec"]["templates"]) == len(job.task) + 1
    assert (entrypoint := workflow["spec"]["templates"][-1])["name"] == "workflow"
    assert len(entrypoint["steps"]) == len(job.task)
    for step, task in zip(entrypoint["steps"], job.task):
        assert len(step) == 1


def test_rendered_job_is_valid(job: JobModel, mock_context: DevAmpelContext):
    from ampel.argo.job import render_job

    manifest = yaml.dump(
        {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "WorkflowTemplate",
            "metadata": {"name": job.name},
        }
        | render_job(mock_context, job),
        sort_keys=False,
    )
    assert not re.search(r"\{\{\s?job\.", manifest), "job expression was translated"
    assert not re.search(r"\{\{\s?task\.", manifest), "task expression was translated"
    try:
        subprocess.run(
            ["argo", "template", "lint", "-"], input=manifest.encode(), check=True
        )
    except FileNotFoundError:
        pytest.skip("linting requires Argo CLI")


def test_validate(bad_job: JobModel, mock_context: DevAmpelContext):
    from ampel.argo.job import render_job

    with pytest.raises(ValidationError):
        render_job(mock_context, bad_job)


def test_validate_job_name(test_data: pathlib.Path):
    from ampel.argo.models import ArgoJobModel

    with (test_data / "ProcessLocalAlerts.yml").open() as f:
        ArgoJobModel(**yaml.safe_load(f))


def test_transform_expressions():

    from ampel.argo.job import ExpressionTransformer, translate_expression

    assert (
        ExpressionTransformer.transform(
            "job.parameters.job", name_mapping={"job": "workflow"}
        )
        == "workflow.parameters.job"
    )

    assert transform_expressions(
        {"foo": {"bar": ["baz", "flim{{ job.parameters.job }}bim"]}},
        transformation=translate_expression,
    ) == {"foo": {"bar": ["baz", "flim{{ workflow.parameters.job }}bim"]}}
