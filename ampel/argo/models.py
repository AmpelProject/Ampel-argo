from pathlib import Path

from pydantic import Field

from ampel.model.job.JobModel import JobModel


class ArgoJobModel(JobModel):
    name: str = Field(
        ...,
        regex="[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*",
        description="Name of the job template. Must be a lowercase RFC 1123 subdomain name.",
    )

    class Config:
        json_encoders = {Path: str}
