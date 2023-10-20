import os
import secrets
from typing import Set, Optional

import yaml
from pydantic import (
    BaseSettings,
    Field,
)


class Settings(BaseSettings):
    root_path: str = Field("", env="ROOT_PATH")
    ampel_config: str = Field("", env="AMPEL_CONFIG")
    container_registry: str = Field(
        "gitlab.desy.de:5555/jakob.van.santen", env="CONTAINER_REGISTRY"
    )
    ampel_image: str = Field(
        "docker-ampel:v0.8", env="AMPEL_IMAGE"
    )
    ampel_secrets: str = Field("ampel-secrets", env="AMPEL_SECRETS")
    image_pull_secrets: list[str] = Field(
        ["desy-gitlab-registry"], env="IMAGE_PULL_SECRETS"
    )
    job_env: list[dict] = Field(
        [
            {
                "name": "AMPEL_CONFIG_resource.mongo",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": "mongo-live-admin-superuser",
                        "key": "connectionString.standard",
                    }
                },
            }
        ],
        env="JOB_ENV",
    )
    service_account: str = Field("argo-workflow", env="SERVICE_ACCOUNT")
    pod_priority_class: Optional[str] = Field(None, env="POD_PRIORITY_CLASS")

    jwt_secret_key: str = Field(secrets.token_urlsafe(64), env="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    allowed_identities: Set[str] = Field(
        {"AmpelProject", "ZwickyTransientFacility"},
        env="ALLOWED_IDENTITIES",
        description="Usernames, teams, and orgs allowed to create workflow templates",
    )

    class Config:
        env_file = ".env"


try:
    with open(os.environ.get("AMPEL_ARGO_CONFIG", "/var/run/ampel-argo/config.yaml")) as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    config = {}

settings = Settings(**config)
