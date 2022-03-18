from typing import Any
from ampel.config.AmpelConfig import AmpelConfig
from ampel.model.UnitModel import UnitModel
from ampel.model.job.JobModel import JobModel, TaskUnitModel, TemplateUnitModel
from ampel.core.AmpelContext import AmpelContext
from ampel.abstract.AbsProcessorTemplate import AbsProcessorTemplate
from importlib import import_module
from pydantic import ValidationError
from contextlib import contextmanager
import json

JOB_TEMPLATE = {
    "name": "ampel-job",
    "inputs": {
        "parameters": [
            {"name": "task"},
            {"name": "name"},
            {"name": "url", "value": ""},
            {"name": "channel", "value": ""},
            {"name": "alias", "value": ""},
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
                "raw": {"data": "{{inputs.parameters.channel}}"},
            },
            {
                "name": "alias",
                "path": "/config/alias.yml",
                "raw": {"data": "{{inputs.parameters.alias}}"},
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
        "image": "gitlab.desy.de:5555/jakob.van.santen/docker-ampel:v0.8",
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
        "env": [
            {
                "name": "AMPEL_CONFIG_resource.mongo",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": "mongo-live-admin-writer",
                        "key": "connectionString.standard",
                    }
                },
            }
        ],
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

    steps = []

    with job_context(context, job) as ctx:
        for task_def in job.task:

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
                unit = UnitModel(**get_unit_model(task))

            if not "AbsEventUnit" in ctx.config._config["unit"][task.unit]["base"]:
                raise ValidationError(
                    [ValueError(f"{task.unit} is not a subclass of AbsEventUnit")],
                    model=JobModel,
                )

            sub_step = {
                "template": "ampel-job",
                "arguments": {
                    "parameters": [
                        {"name": k, "value": compact_json(v)}
                        for k, v in [
                            ("task", unit.dict()),
                            ("channel", job.channel),
                            ("alias", job.alias),
                        ]
                    ]
                    + [{"name": "name", "value": task.title}]
                },
            }

            steps.append(
                [
                    {
                        "name": task.title + (f"-{idx}" if task.multiplier else ""),
                    }
                    | sub_step
                    for idx in range(task.multiplier)
                ]
            )

    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "WorkflowTemplate",
        "metadata": {
            "name": job.name,
            "namespace": "ampel",
            "labels": {
                "example": "true",
            },
        },
        "spec": {
            "templates": [
                JOB_TEMPLATE,
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
            "volumes": [{"name": "secrets", "secret": {"secretName": "ampel-secrets"}}],
            "ttlStrategy": {"secondsAfterCompletion": 1200},
            "podGC": {"strategy": "OnPodCompletion"},
            "workflowMetadata": {
                "labels": {"example": "true"},
            },
        },
    }
