from typing import Any
from ampel.config.AmpelConfig import AmpelConfig
from ampel.model.UnitModel import UnitModel
from ampel.model.job.JobModel import JobModel, TaskUnitModel, TemplateUnitModel
from ampel.core.AmpelContext import AmpelContext
from ampel.abstract.AbsProcessorTemplate import AbsProcessorTemplate
# avoid a circular import in UnitLoader._validate_unit_model
from ampel.abstract.AbsProcessController import AbsProcessController

from importlib import import_module
from pydantic import ValidationError
from contextlib import contextmanager
import json

from typing import Literal

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

def get_job_template(
    image="gitlab.desy.de:5555/jakob.van.santen/docker-ampel:v0.8",
    channel: list[dict[str, Any]] = [],
    alias: dict[Literal["t0", "t1", "t2", "t3"], Any] = {},
) -> dict[str, Any]:
    return {
        "name": "ampel-job",
        "inputs": {
            "parameters": [
                {"name": "task"},
                {"name": "name"},
                {"name": "url", "value": ""},
            ],
            "artifacts": [
                {
                    "name": "task",
                    "path": "/config/task.yml",
                    "raw": {"data": "{{inputs.parameters.task}}"},
                },
                {
                    "name": "channel",
                    "path": "/config/channel.yml",
                    "raw": {"data": compact_json(channel)},
                },
                {
                    "name": "alias",
                    "path": "/config/alias.yml",
                    "raw": {"data": compact_json(alias)},
                },
                {
                    "name": "alerts",
                    "path": "/data/alerts.avro",
                    "http": {"url": "{{ inputs.parameters.url }}"},
                    "optional": True,
                },
            ],
        },
        "outputs": {},
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
    return task.dict(exclude={"title", "multiplier"})


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
            | {"title": model.title, "multiplier": model.multiplier}
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

            title = task.title or f"{job.name}-{num}"

            sub_step = {
                "template": "ampel-job",
                "arguments": {
                    "parameters": [
                        {"name": "name", "value": title},
                        {"name": "task", "value": compact_json(unit.dict())},
                    ]
                },
            }

            steps.append(
                [
                    {
                        "name": title + (f"-{idx}" if task.multiplier else ""),
                    }
                    | sub_step
                    for idx in range(task.multiplier)
                ]
            )

    return {
        "spec": {
            "templates": [
                get_job_template(
                    image=settings.ampel_image,
                    channel=job.channel,
                    alias=job.alias,
                ),
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
                    {"name": "url"},
                    {"name": "name"},
                    {"name": "db"},
                ]
            },
            "serviceAccountName": "argo-workflow",
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
