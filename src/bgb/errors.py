class BgbError(Exception):
    status = 400
    code = "error"


class NotFound(BgbError):
    status = 404
    code = "not_found"


class Conflict(BgbError):
    status = 409
    code = "conflict"


class IntegrityError(BgbError):
    status = 422
    code = "integrity"


class ConfigError(BgbError):
    status = 400
    code = "config"


class UnsupportedSource(BgbError):
    status = 400
    code = "unsupported_source"


class SecretNotFound(BgbError):
    status = 404
    code = "secret_not_found"
