from typing import Annotated, ClassVar

from pydantic import BaseModel, Field


class UserTGData(BaseModel):
    tg_id: Annotated[int, Field(alias="id")]
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    language_code: str = ""
    is_bot: bool = False


class BaseConfig(BaseModel):
    """
    A config payload stored in one `configs` row under `config_name`.
    Subclass it per setting, e.g. `class FeatureFlagsConfig(BaseConfig)`
    with `config_name: ClassVar[str] = "feature_flags"`, and read or write
    it through `ConfigService`.
    """

    config_name: ClassVar[str]
