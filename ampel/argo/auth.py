import jwt

from pydantic import BaseModel, ValidationError
from fastapi import Depends, status, HTTPException
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from .settings import settings

user_bearer = HTTPBearer(scheme_name="Ampel API token")

class User(BaseModel):

    name: str
    orgs: list[str]
    teams: list[str]

    @property
    def identities(self) -> list[str]:
        return [self.name] + self.orgs + self.teams


async def get_user(auth: HTTPAuthorizationCredentials = Depends(user_bearer)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            auth.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        try:
            token_data = User(**payload)
            if not settings.allowed_identities.intersection(token_data.identities):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
            return token_data
        except ValidationError:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
