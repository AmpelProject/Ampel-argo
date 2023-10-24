import re
from pathlib import Path

from pydantic import Field, validator

from ampel.model.job.JobModel import JobModel

from .settings import settings

NAME_REGEX = "[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*"


class ArgoJobModel(JobModel):
    name: str = Field(
        ...,
        regex=NAME_REGEX,
        description="Name of the job template. Must be a lowercase RFC 1123 subdomain name.",
    )
    image: str = Field(settings.ampel_image)

    @validator("image", always=True)
    def qualify_image(cls, v: str):
        if "/" in v:
            if not v.startswith(settings.container_registry):
                raise ValueError(f"image not in approved registry")
            return v
        else:
            return f"{settings.container_registry}/{v}"

    @validator("task")
    def check_title(cls, v):
        for item in v:
            if not re.match(NAME_REGEX, item.title):
                raise ValueError(
                    f"invalid task title '{item.title}' (must be a lowercase RFC 1123 subdomain name)"
                )
        return v

    class Config:
        json_encoders = {Path: str}
