"""A small, context-manager based EDSL for authoring RO-Crates."""

from .conventions import convention
from .core import (
    Node,
    crate,
    dataset,
    discover,
    file,
    link,
    merge,
    person,
    role,
    select,
    software,
    variable,
    workflow,
)

__all__ = [
    "Node",
    "convention",
    "crate",
    "software",
    "dataset",
    "file",
    "person",
    "variable",
    "workflow",
    "select",
    "role",
    "link",
    "merge",
    "discover",
]
