# cscrate

`cscrate` is a small Python library for generating
[RO-Crates](https://w3id.org/ro/crate) from scientific software repositories.
It provides a lightweight, context-manager-based authoring API built on
[`rocrate-py`](https://github.com/ResearchObject/ro-crate-py).

You describe the meaningful structure of a repository in ordinary Python.
`cscrate` can then enrich that structure from conventions already present in
the repository, including:

- `CITATION.cff`
- `pyproject.toml`
- `package.json`
- `README` and `LICENSE` files
- CSVW metadata
- Frictionless Data Packages

There is no separate configuration language or command-line interface. Your
`ro-crate-metadata.py` file is the executable source of truth.

## Requirements

- Python 3.12 or newer

## Installation

Install the project and its dependencies:

```bash
pip install .
```

For development:

```bash
pip install -e ".[test]"
pytest
```

## Quick start

Create `ro-crate-metadata.py` in the root of your repository:

```python
#!/usr/bin/env python3

from cscrate import *

with crate("."):
    with software("."):
        link("author", person("Ada Lovelace"))
        discover()
```

Run it:

```bash
python ro-crate-metadata.py
```

When the outer `crate(...)` context exits, `cscrate` writes
`ro-crate-metadata.json` into the crate root.

## Authoring model

The API consists of entities and operations.

### Entities

```python
software("src")
dataset("data")
file("README.md")
person("Ada Lovelace")
variable("velocity", unit="m/s")
workflow("benchmark")
```

Every entity returns a `Node`. A node can be retained for reuse, entered as a
context, or both:

```python
with software("src") as source:
    source["programmingLanguage"] = "Python"
```

`Node` forwards item and attribute access to the underlying `rocrate-py`
entity. The original entity is also available as `node.entity`.

### Containment through nesting

Crates, software components, datasets, and files are containment entities.
Creating one inside another adds a `hasPart` relationship:

```python
with software("."):
    file("README.md")

    with dataset("data"):
        file("data/results.csv")
```

Path entities use normalized crate-relative paths as their identity. Repeating
`file("README.md")` or `dataset("data")` reuses the existing entity.

### Explicit relationships

People, variables, and workflows are conceptual entities. Creating one does not
implicitly relate it to the current entity; use `link` to state the property:

```python
with software("."):
    link("author", person("Ada Lovelace"))

    with dataset("data"):
        link("variableMeasured", variable("temperature", unit="K"))
```

Bind a conceptual entity when it needs to be reused:

```python
velocity = variable("velocity", unit="m/s")

with dataset("run-1"):
    link("variableMeasured", velocity)

with dataset("run-2"):
    link("variableMeasured", velocity)
```

Conceptual identifiers are deterministic and disambiguated when names collide,
for example `#velocity` and `#velocity-2`.

## Operations

Operations act on the entity in the current `with` context:

```python
role("benchmark")
link("author", person("Jane Roe"))
merge("pyproject.toml")
discover()
```

### Direct metadata

Nodes remain directly editable:

```python
with software(".") as project:
    project["programmingLanguage"] = "Python"
    project.append_to("keywords", "visualization")
```

Convention-derived metadata fills missing properties and does not replace
values that have already been set.

## Discovery

Discovery is explicit. Entity constructors do not inspect the filesystem.

```python
with software("."):
    discover()
```

`discover()` recursively walks the active entity's directory. It:

- honors `.gitignore`;
- ignores `.git`, `__pycache__`, `.venv`, `node_modules`, `build`, and `dist`
  by default;
- creates `Dataset` entities for nonignored subdirectories;
- runs convention handlers for every file it encounters.

An ordinary file is not automatically added to the graph. It becomes a `File`
entity only when something needs to refer to it—for example an explicit
`file(...)` declaration, a `select(...)`, or a convention descriptor that
resolves the file it describes. Other files remain covered by their enclosing
dataset without making the crate graph proportional to every filesystem entry.

An explicitly declared directory is a discovery scope boundary. Enclosing
discovery can enrich that directory from its local convention files, but does
not recurse into it:

```python
with software("."):
    software("component")  # managed explicitly
    discover()
```

To discover the component's contents, place `discover()` inside its own
context:

```python
with software("."):
    with software("component"):
        discover()
    discover()
```

Explicitly declared paths are allowed even when they match an ignore rule.

## Built-in conventions

### Directory metadata

These files describe their containing directory:

| File | Directory type |
| --- | --- |
| `CITATION.cff` | `SoftwareSourceCode` or `Dataset`, according to `type` |
| `pyproject.toml` | `SoftwareSourceCode` |
| `package.json` | `SoftwareSourceCode` |
| `datapackage.json` | `Dataset` |

They may be merged explicitly:

```python
with software("."):
    merge("pyproject.toml")
    merge("CITATION.cff")
```

During discovery, recognized metadata files are consumed as metadata and are
not emitted as ordinary file entities.

### README and LICENSE

README files fill the enclosing entity's `description`. LICENSE and LICENCE
files fill its `license`.

```python
with software("."):
    merge("README.md")
    merge("LICENSE")
```

### CSVW

A CSVW descriptor is recognized by `csv-metadata.json` or a
`*-metadata.json` filename. The descriptor is parsed with `csvw`; each
referenced CSV that exists becomes a file entity, and nonvirtual columns become
`variableMeasured` entities.

```python
with dataset("data"):
    merge("data/table-metadata.json")
```

If a descriptor references a missing CSV, that pair is skipped.

### Frictionless Data

`datapackage.json` creates or enriches a dataset for its directory. Existing
resource files become parts of the dataset, and schema fields become measured
variables.

```python
with dataset("survey"):
    merge("survey/datapackage.json")
```

Missing resource files are skipped.

## Selections and fragments

`select` applies operations to every matching file:

```python
with dataset("results"):
    with select("results/*.vtk"):
        link("author", person("Jane Roe"))
```

A selector containing `#` creates a fragment entity for each file:

```python
velocity = variable("velocity", unit="m/s")

with dataset("results"):
    with select("results/*.vtk#point-data:velocity"):
        link("about", velocity)
```

This produces:

```text
file --hasPart--> fragment --about--> variable
```

## Workflows

Workflows use explicit input and output relationships:

```python
source = software("src")
results = dataset("results")

with workflow("benchmark"):
    link("input", source)
    link("output", results)
```

The prototype represents inputs and outputs as direct entity references rather
than full Workflow RO-Crate formal parameters.

## Custom convention handlers

Use `@convention` to teach both `merge()` and `discover()` about another
metadata format:

```python
import json

from cscrate import convention


@convention
def codemeta(path, context):
    if path.name != "codemeta.json":
        return False

    data = json.loads(path.read_text())
    context["name"] = data["name"]
    return True
```

A handler receives:

- `path`: the candidate filesystem path;
- `context`: the enclosing `Node`.

It returns `True` when it handled the file, or `False` when the next handler
should be tried. Handlers registered by user code are tried before built-ins,
so they can override built-in behavior.

Handlers should:

- perform cheap recognition before parsing;
- own the complete behavior of their convention;
- manipulate explicit nodes directly rather than calling authoring operations;
- use the builder's path resolution methods when creating path entities;
- verify paired or referenced files exist before creating entities for them.

During discovery, a `True` result means the metadata file is consumed and is
not emitted as an ordinary `File`.

## Complete example

```python
from cscrate import *

with crate("."):
    with software(".") as project:
        project["programmingLanguage"] = "Python"
        project.append_to("keywords", "research software")

        link("author", person("Ada Lovelace"))
        merge("pyproject.toml")
        merge("CITATION.cff")

        with software("src") as source:
            discover()

        with dataset("data") as data:
            velocity = variable("velocity", unit="m/s")
            link("variableMeasured", velocity)

            with select("data/results/*.vtk#point-data:velocity"):
                link("about", velocity)

            discover()

        with workflow("benchmark"):
            link("input", source)
            link("output", data)

        discover()
```

## Scope

`cscrate` is intentionally small. It is a convenient authoring layer over
`rocrate-py`, not a comprehensive RO-Crate framework. Direct access to the
underlying entities remains available when the built-in DSL or conventions do
not cover a use case.
