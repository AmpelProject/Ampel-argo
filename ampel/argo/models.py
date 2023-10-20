from pathlib import Path

from pydantic import Field, validator

from ampel.model.job.JobModel import JobModel

from .settings import settings


class ArgoJobModel(JobModel):
    name: str = Field(
        ...,
        regex="[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*",
        description="Name of the job template. Must be a lowercase RFC 1123 subdomain name.",
    )
    image: str = Field(settings.ampel_image)

    @validator("image", always=True)
    def qualify_image(cls, v: str):
        if "/" in v:
            if not v.startswith(settings.container_registry):
                raise ValueError(f"image not in approved registry")
            else:
                return f"{settings.container_registry}/{v}"
        return v

    class Config:
        json_encoders = {Path: str}
