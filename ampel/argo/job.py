import ast
from typing import Any, Callable
from ampel.config.AmpelConfig import AmpelConfig
from ampel.model.UnitModel import UnitModel
from ampel.model.job.JobModel import (
    InputArtifact,
    InputParameter,
    JobModel,
    TaskUnitModel,
    TemplateUnitModel,
    OutputParameter,
    InputArtifactHttpSource,
    ExpandWithItems,
    ExpandWithSequence,
)
from ampel.core.AmpelContext import AmpelContext
from ampel.abstract.AbsProcessorTemplate import AbsProcessorTemplate

# avoid a circular import in UnitLoader._validate_unit_model
from ampel.abstract.AbsProcessController import AbsProcessController

from importlib import import_module
from pydantic import BaseModel, ValidationError
from contextlib import contextmanager
from functools import singledispatch, partial
import json

from typing import Literal, Union

from .settings import settings

# things that might be settable
# job template: will use ampel-job
# - image
# - channel
# - alias
# - extra parameters (also appears in step definition)
# - extra artifacts
# - env vars
# - secret mounts
# spec:
# - extra parameters (that may also appear in job template)
# - volumes (for secrets)
# - image pull secrets


class ExpressionTransformer(ast.NodeVisitor):
    """Translate top-level names"""

    def __init__(self, name_mapping: dict[str, str]):
        self._name_mapping = name_mapping
        self._output = ""

    def visit_Name(self, node: ast.Name):
        super().generic_visit(node)
        self._output += self._name_mapping.get(node.id, node.id)

    def visit_Attribute(self, node: ast.Attribute):
        super().generic_visit(node)
        self._output += "." + node.attr

    @classmethod
    def transform(cls, expression: str, name_mapping: dict[str, str]):
        self = cls(name_mapping)
        self.visit(ast.parse(expression, mode="eval"))
        return self._output


def translate_expression(expression: str) -> str:
    return (
        "{{ "
        + ExpressionTransformer.transform(
            expression, name_mapping={"job": "workflow", "task": "steps"}
        )
        + " }}"
    )


@singledispatch
def to_argo(model) -> dict:
    return JobModel.transform_expressions(model.dict(), translate_expression)


@to_argo.register
def _(model: list) -> dict:
    return [to_argo(element) for element in model]


@to_argo.register
def _(model: OutputParameter) -> dict:
    return JobModel.transform_expressions(
        {
            "name": model.name,
            "valueFrom": {
                "path": str(model.value_from.path),
                "default": model.value_from.default,
            },
        },
        translate_expression,
    )


@to_argo.register
def _(model: ExpandWithItems):
    return {"withItems": model.items}


@to_argo.register
def _(model: ExpandWithSequence):
    return {"withSequence": model.sequence.dict()}


@to_argo.register
def _(model: InputArtifact) -> dict:
    return JobModel.transform_expressions(
        (
            model.dict()
            | {
                "path": str(model.path),
            }
        ),
        translate_expression,
    )


def get_template_for_task(
    job: JobModel,
    task: Union[TaskUnitModel, TemplateUnitModel],
    image="gitlab.desy.de:5555/jakob.van.santen/docker-ampel:v0.8",
) -> dict[str, Any]:
    return {
        "name": task.title,
        "inputs": {
            "parameters": [
                {"name": "task"},
                {"name": "name"},
            ]
            + to_argo(task.inputs.parameters),
            "artifacts": [
                {
                    "name": "task",
                    "path": "/config/task.yml",
                    "raw": {"data": "{{inputs.parameters.task}}"},
                },
                {
                    "name": "channel",
                    "path": "/config/channel.yml",
                    "raw": {"data": compact_json(job.channel)},
                },
                {
                    "name": "alias",
                    "path": "/config/alias.yml",
                    "raw": {"data": compact_json(job.alias)},
                },
            ]
            + to_argo(task.inputs.artifacts),
        },
        "outputs": {"parameters": to_argo(task.outputs.parameters)},
        "metadata": {},
        "container": {
            "name": "main",
            "image": image,
            "command": [
                "ampel",
                "process",
                "--config",
                "/opt/env/etc/ampel.yml",
                "--secrets",
                "/config/secrets/secrets.yaml",
                "--channel",
                "/config/channel.yml",
                "--alias",
                "/config/alias.yml",
                "--db",
                "{{workflow.parameters.db}}",
                "--schema",
                "/config/task.yml",
                "--name",
                "{{inputs.parameters.name}}",
            ],
            "env": settings.job_env,
            "resources": {},
            "volumeMounts": [
                {
                    "name": "secrets",
                    "readOnly": True,
                    "mountPath": "/config/secrets",
                }
            ],
        },
    }


def get_unit_model(task: TaskUnitModel) -> dict[str, Any]:
    """get dict representation of UnitModel from TaskUnitModel"""
    return task.dict(exclude={"title", "expand_with", "inputs", "outputs"})


def render_task_template(ctx: AmpelContext, model: TemplateUnitModel) -> TaskUnitModel:
    """
    Resolve and validate a full AbsEventUnit config from given template
    """
    if model.template not in ctx.config._config["template"]:
        raise ValueError(f"Unknown process template: {model.template}")

    fqn = ctx.config._config["template"][model.template]
    class_name = fqn.split(".")[-1]
    Tpl = getattr(import_module(fqn), class_name)
    if not issubclass(Tpl, AbsProcessorTemplate):
        raise ValueError(f"Unexpected template type: {Tpl}")

    tpl = Tpl(**model.config)

    return TaskUnitModel(
        **(
            tpl.get_model(ctx.config._config, model.dict()).dict()
            | {
                "title": model.title,
                "expand_with": model.expand_with,
            }
        )
    )


@contextmanager
def job_context(ctx: AmpelContext, job: JobModel):
    """Add custom channels and aliases defined in the job"""
    old_config = ctx.config
    try:
        config = AmpelConfig(old_config.get(), freeze=False)
        config_dict = config._config
        for c in job.channel:
            dict.__setitem__(config_dict["channel"], str(c["channel"]), c)

        for k, v in job.alias.items():
            if "alias" not in config_dict:
                dict.__setitem__(config_dict, "alias", {})
            for kk, vv in v.items():
                if k not in config_dict["alias"]:
                    dict.__setitem__(config_dict["alias"], k, {})
                dict.__setitem__(config_dict["alias"][k], kk, vv)
        config.freeze()
        ctx.config = config
        ctx.loader.config = config
        yield ctx
    finally:
        ctx.config = old_config
        ctx.loader.config = old_config


compact_json = json.JSONEncoder(separators=(",", ":")).encode


def render_job(context: AmpelContext, job: JobModel):
    """Render Ampel job into an Argo workflow template spec"""

    steps = []
    templates = []

    with job_context(context, job) as ctx:
        for num, task_def in enumerate(job.task):

            task = (
                render_task_template(ctx, task_def)
                if isinstance(task_def, TemplateUnitModel)
                else task_def
            )
            # always raise exceptions
            if task.override is None:
                task.override = {}
            task.override["raise_exc"] = True

            with ctx.loader.validate_unit_models():
                unit: UnitModel = UnitModel(**get_unit_model(task))

            if not "AbsEventUnit" in ctx.config._config["unit"][task.unit]["base"]:
                raise ValidationError(
                    [[ValueError(f"{task.unit} is not a subclass of AbsEventUnit")]],
                    model=JobModel,
                )

            templates.append(
                get_template_for_task(
                    job,
                    task,
                    image=settings.ampel_image,
                )
            )

            sub_step = {
                "name": task.title,
                "template": task.title,
                "arguments": {
                    "parameters": [
                        {"name": "name", "value": task.title},
                        {
                            "name": "task",
                            "value": compact_json(
                                job.transform_expressions(
                                    unit.dict(),
                                    translate_expression,
                                )
                            ),
                        },
                    ]
                },
            }
            if task.expand_with:
                sub_step |= to_argo(task.expand_with)

            steps.append([sub_step])

    return {
        "spec": {
            "templates": templates
            + [
                {
                    "name": "workflow",
                    "inputs": {},
                    "outputs": {},
                    "metadata": {},
                    "steps": steps,
                },
            ],
            "entrypoint": "workflow",
            "arguments": {
                "parameters": [
                    {"name": "name", "value": job.name},
                    {"name": "db", "value": job.name},
                ]
                + [p.dict() for p in job.parameters]
            },
            "serviceAccountName": settings.service_account,
            "volumes": [
                {"name": "secrets", "secret": {"secretName": settings.ampel_secrets}}
            ],
            "ttlStrategy": {"secondsAfterCompletion": 1200},
            "podGC": {"strategy": "OnPodCompletion"},
            "workflowMetadata": {
                "labels": {"example": "true"},
            },
            "imagePullSecrets": [{"name": n} for n in settings.image_pull_secrets],
        },
    }


def entrypoint():
    from argparse import ArgumentParser, FileType
    from ampel.core.AmpelContext import AmpelContext
    from .models import ArgoJobModel
    import yaml

    parser = ArgumentParser()
    parser.add_argument("--config", default="ampel.yaml")
    parser.add_argument("job", type=FileType("r"))

    args = parser.parse_args()
    ctx = AmpelContext.load(args.config)

    model = ArgoJobModel(**yaml.safe_load(args.job))

    resource = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "WorkflowTemplate",
        "metadata": {"name": model.name},
    } | render_job(ctx, model)

    print(yaml.dump(resource, sort_keys=False))
