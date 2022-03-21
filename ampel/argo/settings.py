import secrets
from typing import Set

from pydantic import (
    BaseSettings,
    Field,
)


class Settings(BaseSettings):
    root_path: str = Field("", env="ROOT_PATH")
    ampel_config: str = Field("", env="AMPEL_CONFIG")
    ampel_image: str = Field("gitlab.desy.de:5555/jakob.van.santen/docker-ampel:v0.8", env="AMPEL_IMAGE")
    ampel_secrets: str = Field("ampel-secrets", env="AMPEL_SECRETS")
    image_pull_secrets: list[str] = Field(["desy-gitlab-registry"], env="IMAGE_PULL_SECRETS")

    jwt_secret_key: str = Field(secrets.token_urlsafe(64), env="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    allowed_identities: Set[str] = Field(
        {"AmpelProject", "ZwickyTransientFacility"},
        env="ALLOWED_IDENTITIES",
        description="Usernames, teams, and orgs allowed to create workflow templates",
    )

    class Config:
        env_file = ".env"


settings = Settings()