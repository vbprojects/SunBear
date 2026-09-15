"""Shared target validation and safe encoders."""

import copy
from ..emit import Batch, Artifact


class BaseTarget:
    def session(self):
        return copy.deepcopy(self)

    def artifacts(self, declarations):
        return ()


def identifier(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Invalid SQL identifier")
    return '"' + value.replace('"', '""') + '"'
