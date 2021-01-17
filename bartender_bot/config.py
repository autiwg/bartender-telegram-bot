from dynaconf import Dynaconf, Validator

settings = Dynaconf(
    envvar_prefix="DYNACONF",
    settings_files=["settings.toml", ".secrets.toml"],
    validators=[
        Validator("api_host", must_exist=True, cont="http"),
        Validator("telegram_token", must_exist=True),
        Validator("admin_user", must_exist=True),
    ],
)
