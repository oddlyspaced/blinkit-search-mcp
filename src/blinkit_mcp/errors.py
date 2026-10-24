"""Error type and error codes shared by all modules."""

NO_LOCATION = "no_location"
BLOCKED = "blocked"
NOT_SERVICEABLE = "not_serviceable"
NOT_FOUND = "not_found"
UPSTREAM_CHANGED = "upstream_changed"
NETWORK = "network"
BAD_INPUT = "bad_input"


class BlinkitError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
