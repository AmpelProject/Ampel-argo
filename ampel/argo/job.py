import ast
from typing import Any
from ampel.argo.models import ArgoJobModel
from ampel.config.AmpelConfig import AmpelConfig
from ampel.log.AmpelLogger import AmpelLogger
from ampel.model.UnitModel import UnitModel
from ampel.model.job.utils import transform_expressions
from ampel.model.job.JobModel import (
    JobModel,
    TaskUnitModel,
    TemplateUnitModel,
)
from ampel.model.job.InputArtifact import InputArtifact
from ampel.model.job.OutputParameter import OutputParameter
from ampel.model.job.ExpandWithItems import ExpandWithItems
from ampel.model.job.ExpandWithSequence import ExpandWithSequence
from ampel.core.AmpelContext import AmpelContext
from ampel.abstract.AbsProcessorTemplate import AbsProcessorTemplate


from importlib import import_module
from pydantic import ValidationError
from pydantic.error_wrappers import ErrorWrapper
from contextlib import contextmanager
from functools import singledispatch
import json

from typing import Union

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
    return transform_expressions(model.dict(), translate_expression)


@to_argo.register # type: ignore[arg-type]
def _(model: list) -> list[dict]:
    return [to_argo(element) for element in model]


@to_argo.register
def _(model: OutputParameter) -> dict:
    return transform_expressions(
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
    return transform_expressions(
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
                {"name": "name"},
            ]
            + to_argo(task.inputs.parameters), # type: ignore[operator]
            "artifacts": [
                {
                    "name": "__task",
                    "path": "/config/task.yml",
                },
                {
                    "name": "__channel",
                    "path": "/config/channel.yml",
                    "raw": {"data": compact_json([c.dict() for c in job.channel])},
                },
                {
                    "name": "__alias",
                    "path": "/config/alias.yml",
                    "raw": {"data": compact_json(job.alias)},
                },
            ]
            # explicitly avoid setting source parameters for input artifacts
            # to allow expressions to be expanded at step level
            + [
                {"name": artifact.name, "path": str(artifact.path)}
                for artifact in task.inputs.artifacts
            ],
        },
        "outputs": {
            "parameters": to_argo(task.outputs.parameters),
            "artifacts": to_argo(task.outputs.artifacts),
        },
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
            tpl.get_model(ctx.config._config, AmpelLogger.get_logger()).dict()
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
            dict.__setitem__(config_dict["channel"], str(c.channel), c.dict())

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


def render_job(context: AmpelContext, job: ArgoJobModel):
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
                try:
                    unit: UnitModel = UnitModel(**get_unit_model(task))
                except TypeError as exc:
                    # extract and raise inner ValidationError
                    raise exc.args[0] from None
                except ValueError as exc:
                    # wrap ValueError from missing unit
                    raise ValidationError([ErrorWrapper(exc, "unit")], model=UnitModel) from None

            if not "AbsEventUnit" in ctx.config._config["unit"][task.unit]["base"]:
                raise ValidationError(
                    [[ValueError(f"{task.unit} is not a subclass of AbsEventUnit")]],
                    model=JobModel,
                )

            templates.append(
                get_template_for_task(
                    job,
                    task,
                    image=job.image,
                )
            )

            sub_step = {
                "name": task.title,
                "template": task.title,
                "arguments": {
                    "parameters": [{"name": "name", "value": task.title}],
                    "artifacts": [
                        {
                            "name": "__task",
                            "raw": {
                                "data": compact_json(
                                    transform_expressions(
                                        unit.dict(),
                                        translate_expression,
                                    )
                                )
                            },
                        },
                    ]
                    # drop path, as argo will ignore it in a step spec
                    + [(d, d.pop("path"))[0] for d in to_argo(task.inputs.artifacts)],
                },
            }
            if task.expand_with:
                sub_step |= to_argo(task.expand_with)

            steps.append([sub_step])

    workflow_template = {
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
            "imagePullSecrets": [{"name": n} for n in settings.image_pull_secrets],
        },
    }

    if settings.pod_priority_class:
        workflow_template["spec"]["podPriorityClassName"] = settings.pod_priority_class

    return workflow_template


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
