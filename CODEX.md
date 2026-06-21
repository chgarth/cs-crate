# CODEX.md

## Overview

`cscrate` is a small Python package providing a lightweight embedded DSL (EDSL)
for generating [RO-Crates](https://w3id.org/ro/crate) from scientific software
repositories.

This is not a comprehensive framework. It is a lean proof-of-concept that
demonstrates:

- convention-based metadata discovery,
- composition of metadata from multiple sources,
- a pleasant Python authoring experience built on `rocrate-py`,
- generation of valid RO-Crates.

The target audience is computer scientists who are comfortable writing Python.

The design is based on **conventions, not scaffolds**. A convention is a
commonly used pattern that carries agreed-upon semantics — `CITATION.cff`,
`pyproject.toml`, `package.json`, `README.md`, CSVW metadata, Frictionless Data
packages, data-fragment selectors. The system recognises and leverages such
conventions. It does not impose a repository structure.

Repositories may contain multiple software components, multiple languages,
nested packages, nested workflows, and mixed software and data. The system
remains composable and permissive.

---

## Motivation

Describing a research repository as an RO-Crate by hand is tedious and
error-prone: the metadata duplicates information that already lives in the
repository (in `CITATION.cff`, `pyproject.toml`, CSVW sidecars, and so on), and
keeping the two in sync is manual work. Existing tooling sits at two extremes.
Writing `rocrate-py` directly is precise but verbose, and it offers no
convention awareness — you wire every entity and relationship yourself. The
`rocrate init` command, at the other extreme, dumps every file and directory as
an untyped entity with no metadata enrichment and no way to reconcile against
hand-authored intent.

`cscrate` aims for the middle: a concise authoring layer where the author states
*intent* ("this directory is a software component", "this dataset measures
velocity") and lets convention discovery fill in the rest from the files that
are already present. The author's file is the single source of truth, and it is
ordinary executable Python — no separate metadata language to learn, and no
loss of access to the underlying crate when the conventions don't cover a case.

---

## Design Goals

1. **Conventions over configuration.** Metadata is harvested from the
   established files that already exist in a repository. The author declares
   intent; discovery supplies detail.

2. **A thin layer over `rocrate-py`.** The EDSL is a builder over `rocrate-py`
   entities. There is no separate declaration graph, no lowering phase, and no
   semantic compilation stage. The whole implementation should remain
   understandable in a few hundred lines (excluding the convention parsers).

3. **The authoring file is authoritative.** The author writes
   `ro-crate-metadata.py`, which generates `ro-crate-metadata.json`. The file is
   executed directly. There is no command-line tool.

4. **A single, uniform authoring style.** All structure is expressed with `with`
   context managers. There is exactly one way to nest entities.

5. **Permissive, not prescriptive.** The EDSL never prevents direct access to
   the underlying `rocrate-py` entities, and never imposes a repository layout.

6. **Deterministic output.** Generating the crate twice from an unchanged
   repository produces identical metadata.

---

## Authoring Model

The author writes a file named `ro-crate-metadata.py`:

```python
#!/usr/bin/env python3

from cscrate import *

with crate("."):
    with software("."):
        ...  # see below
```

Running it generates `ro-crate-metadata.json` in the crate root:

```bash
python ro-crate-metadata.py
```

The crate is written automatically when the `with crate(...)` block exits.

There is no helper CLI. The authoring file is the only entry point, which keeps
the system honest: there is no hidden behaviour available through a tool but not
through the script itself.

---

## Architecture

```
Python EDSL  (with-context builder)
      |
      v
Crate Builder  (active-entity stack, get-or-create, hasPart wiring)
      |
      v
rocrate-py entities
      |
      v
ro-crate-metadata.json
```

The builder maintains a **stack of active targets** (implemented with a
`contextvars.ContextVar`). Entering a context entity pushes a target; exiting
pops it. Operations always act on the top of the stack.

Each entity the author touches is a thin wrapper (`Node`) holding the real
`rocrate-py` entity. The wrapper is a context manager and forwards item and
attribute access to the underlying entity, so direct manipulation remains
available:

```python
with software(".") as sw:
    sw["programmingLanguage"] = "Python"   # forwarded to the rocrate-py entity
    sw.append_to("keywords", "visualization")
    sw.entity                              # the underlying rocrate-py object
```

Path entities are created by **get-or-create**: `software("src")` either
retrieves the existing entity for `src/` or adds it via `rocrate-py`, then
ensures the appropriate `@type`. Nesting is realised by appending the child to
the current entity's `hasPart`.

---

## Entities, Operations, and Contexts

The DSL has just **entities** and **operations**. Every entity can open a
**context**.

### Entities

`crate`, `software`, `dataset`, `file`, `person`, `variable`, `workflow`, and
the selection produced by `select`.

Every entity-creating call returns a handle (`Node`) that is also a context
manager. So *any* entity may be:

- bound to a name — `velocity = variable("velocity")` — to reference later;
- entered with `with` — `with software("src"):` — to make it the current target;
- both — `with software("src") as sw:`.

Use `as name` whenever you need the handle elsewhere; otherwise omit it.

### What entering a context does

Entering an entity pushes it onto the active-target stack and makes it the
current entity; operations inside act on it. Exiting pops it. `with crate(...)`
additionally writes the crate on exit. Entering a *conceptual* entity simply
makes it current so you can set *its own* metadata; it establishes no
relationship by itself.

### How entities relate

There are two relationship mechanisms, and which one applies depends on the
entity kind:

- **Containment entities** (`crate`, `software`, `dataset`, `file`) relate
  **implicitly by nesting**: a containment entity created inside another
  attaches to it via `hasPart`. `hasPart` is unambiguous, so nesting is enough.
- **Conceptual entities** (`person`, `variable`, `workflow`) relate **only by
  explicit `link`**. Creating one never relates it to anything on its own —
  because the right property is a choice (a person may be `author`, `creator`,
  or `contributor`; a variable may be `variableMeasured` or `about`). You state
  the property yourself, and the entity argument may be built ad hoc in the call
  or bound beforehand:

```python
with software("."):
    link("author", person("Christoph Garth"))      # built ad hoc, related by link

    ada = person("Ada Lovelace")                    # bound for reuse
    link("contributor", ada)                        # same entity, a different relation

    with dataset("data"):
        link("variableMeasured", variable("velocity", unit="m/s"))   # variable, ad hoc
```

Because creation never auto-relates a conceptual entity, conceptual entities may
be created at any scope inside the crate without accidentally attaching to it.
To enrich a conceptual entity's own metadata before linking it, enter it with
`with` and bind it:

```python
with variable("velocity", unit="m/s") as velocity:
    velocity["description"] = "Fluid speed magnitude"
with dataset("data"):
    link("variableMeasured", velocity)              # reuse the same variable
```

A **selection** (`select`) is a context over a *set* of pre-existing targets;
operations such as `link` inside it broadcast to every member. Select
homogeneous sets so a single property fits all members (e.g. `variableMeasured`
for whole files, `about` for fragments).

### Operations

`role`, `link`, `merge`, `discover`.

An operation acts on the current entity (the top of the stack). The current
entity is always the *subject*; any related entity is passed as an argument.
There are no target-override parameters — an operation always applies *here*.

---

## Identity Model

The identity model must be easy to reason about.

**Path entities** are identified by their normalised, crate-relative path.

```python
software("src")
software("src")     # the same RO-Crate entity
```

A single path may carry multiple semantic types. Declaring both `software(".")`
and `dataset(".")` enriches one entity:

```json
{ "@id": "./", "@type": ["Dataset", "SoftwareSourceCode"] }
```

**Conceptual entities** use Python object identity. Reusing the same object
means the same entity; reconstructing means a distinct entity.

```python
velocity = variable("velocity")
# referencing `velocity` twice -> one shared entity

variable("velocity")
variable("velocity")   # two distinct entities
```

Conceptual entities are assigned stable, deterministic identifiers (e.g.
`#velocity`), disambiguated on collision (`#velocity`, `#velocity-2`), so that
output is reproducible.

---

## Entities

```python
person("Christoph Garth")
variable("velocity", unit="m/s")
software("src")
dataset("data")
file("README.md")
workflow("benchmark")
```

Every one of these can be entered with `with` or bound to a name. For
containment entities, nesting implies `hasPart`:

```python
with software("."):
    file("README.md")
    with dataset("data"):
        file("results.vtk")
```

```
software .
├── README.md
└── data
    └── results.vtk
```

A child created inside a containment context is attached directly to that
context. Note that `rocrate-py` also links freshly added data entities from the
root data entity; an entity reachable indirectly (root → software → file) is
still a valid data entity, so a nested file need not also be listed at the root.
Whether the redundant root link is trimmed is an output-tidiness choice, not a
correctness requirement.

---

## Variables and Measurement

Variables are reusable conceptual entities. Relate a variable to a dataset or
file with `link("variableMeasured", ...)`, and to a fragment with
`link("about", ...)`. The variable may be built ad hoc in the `link` call:

```python
with dataset("data"):
    link("variableMeasured", variable("velocity", unit="m/s"))
```

```json
{ "@id": "#velocity", "name": "velocity", "unitText": "m/s" }
{ "@id": "data/", "variableMeasured": { "@id": "#velocity" } }
```

To share one variable across several entities, bind it once and pass the handle;
this references the existing entity rather than creating a new one (object
identity):

```python
velocity = variable("velocity", unit="m/s")
with dataset("run1"):
    link("variableMeasured", velocity)
with dataset("run2"):
    link("variableMeasured", velocity)
```

The property is always the author's explicit choice — `variableMeasured` for a
file or dataset, `about` for a fragment (the ARC Datamap RO-Crate style) — so
there is no guessing about which relation a variable carries.

---

## Selection and Fragment Annotation

`select` defines a set of files or parts of files, so that further metadata can
be applied to all of them at once. It is a **selection context**: operations
inside it broadcast to every member, and it creates no children of its own.

```python
with dataset("data"):
    # one author across several whole files
    with select("results/*.vtk"):
        link("author", person("Jane Roe"))

    # one variable as about across many fragments
    with select("results/*.vtk#point-data:velocity"):
        link("about", velocity)
```

Keep a selection homogeneous so a single property fits every member —
`variableMeasured` or `link`ed roles for whole files, `about` for fragments.

A fragment selector (`file#fragment`) creates a fragment entity that is a
`hasPart` of the file and points `about` the relevant variable:

```
file --hasPart--> fragment --about--> variable
```

Selection is idempotent: re-selecting the same pattern returns the same
file/fragment entities and enriches them rather than duplicating.

---

## Operations

```python
role("benchmark")                              # role of the current entity
link("author", person("Jane Roe"))             # current entity --author--> a person
link("variableMeasured", variable("velocity")) # current entity --variableMeasured--> a variable
merge("pyproject.toml")                        # merge external metadata into the current entity
discover()                                     # fill gaps below the current entity
```

`merge` imports metadata from an external source into the current entity. It may
internally create additional entities — for example, `merge` of a CSVW or
Frictionless descriptor may create variables and selectors derived from the
described schema.

---

## Discovery

Discovery is **explicit**: entity constructors never inspect the filesystem;
only `discover()` does.

`discover()` recursively traverses the filesystem subtree rooted at the current
entity's directory and reconciles what it finds against the crate, projecting
the filesystem's containment structure onto the RO-Crate's `hasPart` hierarchy.
For each path it visits (honouring `.gitignore`), it either **enriches** the
entity that already represents that path or, where the path warrants an entity,
**creates** one and attaches it to the entity representing its parent directory.
A represented subdirectory thus becomes a `Dataset` that is `hasPart` of its
parent, so containment on disk becomes containment in the crate. While walking,
it applies the local convention detectors (see *Conventions*) to enrich entities
from the metadata files it encounters.

The projection is **selective, not exhaustive**. Discovery materialises an
entity only where one is warranted — a referenced path, or a directory marked by
a convention (see *What discovery materialises*) — and creates only the
intermediate `Dataset`s needed to anchor such entities in the hierarchy. Paths
that carry no meaning are not turned into entities; they are covered collectively
by the nearest enclosing `Dataset`. The crate hierarchy therefore mirrors the
filesystem hierarchy for the parts that are represented, and no further.

```python
with software("src"):
    discover()       # walk src/, enriching and creating entities below it
```

Discovery is rooted at the enclosing entity and may appear at multiple levels:

```python
with software("."):
    with dataset("data"):
        discover()   # fills gaps below data/
    discover()       # fills gaps below the software component
```

### What discovery materialises

Discovery does **not** create a `File` entity for every file it walks. A file
earns its own entity only when there is a reason to reference it by identifier:

- the author named it, or it is annotated by a `select`/fragment, or it is a
  workflow input/output, or it is itself a recognised artifact (a workflow, a
  main script); **or**
- a directory-marking convention designates its directory as a component (see
  *Conventions*).

Files with no referent are covered by their containing `Dataset` and are not
enumerated individually. A directory of thousands of nameless outputs becomes a
single `Dataset`, not thousands of `File` entities. This keeps the metadata
proportional to the meaningful structure rather than to the raw file count.

### Discovery philosophy

Discovery fills gaps. It must not reinterpret explicit declarations. An explicit
declaration claims semantic ownership of a path; discovery may enrich such a
path but must not reclassify it or create a competing entity. For every
discovered path:

```
path already an explicitly declared entity?
    yes -> reuse it; do NOT recurse into its contents (scope boundary)
    no  -> enrich if it already exists, else create if it warrants one;
           then recurse
```

A declared directory entity is a **scope boundary**. When discovery reaches a
path the author has already declared, it reuses that entity but does not descend
into it — the directory's contents are governed by that entity's own
declaration, including any `discover()` placed inside it. This keeps a nested
discovery from being re-walked by an enclosing one, and stops one scope's
discovery from populating another component's internals. The corollary:
declaring a directory *without* an inner `discover()` means "I am describing this
myself", and an enclosing `discover()` will not fill it.

Because this reconciliation keys on the normalised crate-relative path, it
applies only to path-identified directory entities. A `#`-identified conceptual
Dataset or an absolute-URI (web-based) Dataset has no corresponding filesystem
path, so it is neither matched nor descended into during the walk.

Convention detectors are **local**. Discovery never performs repository-wide
reasoning: it does not determine a primary component, collapse components, or
move metadata between scopes.

### Git integration

Discovery respects `.gitignore` using Git wildmatch semantics (via `pathspec`),
so the following are ignored by default:

```
.git/  __pycache__/  .venv/  node_modules/  build/  dist/
```

Explicit declarations always override ignore rules: `dataset("build/results")`
works even if `build/` is gitignored.

---

## Conventions

Convention files are metadata sources. They fall into three modes.

### Directory-marking conventions

The presence of one of these in a directory induces an entity **for that
directory** and merges its metadata into it.

| File | Induces |
| --- | --- |
| `CITATION.cff` | a component for the directory, typed by the CFF `type:` field (`software` or `dataset`) |
| `pyproject.toml` | a `software` component for the directory |
| `package.json` | a `software` component for the directory |
| `datapackage.json` | a `dataset` (Frictionless Data Package) for the directory |

For example, finding `tools/sim/CITATION.cff` is equivalent to:

```python
with software("tools/sim"):     # or dataset(...), per the CFF type
    merge("tools/sim/CITATION.cff")
```

A `CITATION.cff` in a subdirectory therefore makes that subdirectory its own
component, regardless of what encloses it.

### Enclosing-entity enrichers

`README.md` and `LICENSE` merge into the entity that encloses them. They may
additionally be represented as file entities.

### Sibling-file metadata

These describe a specific data file and merge into it, potentially inducing
variables and selectors.

| Pattern | Merges into |
| --- | --- |
| `table-metadata.json` (CSVW) | `table.csv` |
| Frictionless resource entry | each declared resource file |

For CSVW:

```python
with file("table.csv"):
    merge("table-metadata.json")
```

### Frictionless Data

A `datapackage.json` describes a Data Package and its resources. Discovery maps
it as follows:

- the descriptor's directory becomes a `dataset`;
- each Data Resource (`path`) becomes a `file` that is a `hasPart` of the
  dataset, enriched with the resource's `name`, `format` / `mediatype`, etc.;
- each Table Schema `field` becomes a `variable` (`variableMeasured`), carrying
  the field's `name`, `title`, `description`, and type.

Conceptually:

```python
with dataset("survey"):
    merge("survey/datapackage.json")   # creates resource files + field variables
```

This mirrors the CSVW handling: a tabular schema is lifted into variables that
the dataset measures, with selectors where appropriate.

---

## Workflows

Workflows are reusable conceptual entities. Inputs and outputs reference
entities rather than paths, which avoids path resolution and gives stable
references. Like every other relationship, they are expressed with explicit
operations inside the workflow's context rather than as constructor arguments:

```python
data = dataset("data")

with workflow("benchmark"):
    link("output", data)     # workflow --output--> the data entity, not a path
```

This is deliberately light: the prototype models inputs and outputs as direct
references, without the FormalParameter machinery of the full Workflow RO-Crate
profile.

---

## Complete Example

```python
from cscrate import *

with crate("."):                          # writes ro-crate-metadata.json on exit

    with software(".") as root:           # "./" becomes Dataset + SoftwareSourceCode (reclassification)
        root["programmingLanguage"] = "Python"        # direct access to the rocrate-py entity
        root.append_to("keywords", "visualization")
        role("benchmark")

        link("author", person("Christoph Garth"))     # conceptual entity built ad hoc, related by link
        ada = person("Ada Lovelace")                  # bound for reuse
        link("contributor", ada)                      # same entity, a different relation

        merge("pyproject.toml")           # directory-marking convention
        merge("CITATION.cff")             # directory-marking convention (typed by the CFF `type:`)
        merge("README.md")                # enclosing-entity enricher
        file("README.md")                 # README also represented as a File entity

        with software("src") as src:      # nested containment -> hasPart
            discover()                    # discovery rooted at src/

        with software("viz"):             # another nested component
            merge("viz/package.json")     # directory-marking convention (npm)

        with dataset("data") as data:     # nested containment -> hasPart
            link("variableMeasured", variable("temperature", unit="K"))   # variable built ad hoc

            with variable("velocity", unit="m/s") as velocity:   # bound; enter to set its own metadata
                velocity["description"] = "Fluid speed magnitude"
            link("variableMeasured", velocity)                   # reuse the same variable

            with file("data/measurements.csv"):              # file used as a context
                merge("data/measurements-metadata.json")     # CSVW -> columns become variables

            with dataset("data/survey"):
                merge("data/survey/datapackage.json")        # Frictionless -> resources + field variables

            with select("data/results/*.vtk#point-data:velocity"):   # selection broadcasts
                link("about", velocity)                      # each fragment -> about velocity

            discover()                    # reconcile data/: enrich declarations, fold bulk leaves

        with workflow("workflows/benchmark"):   # inputs/outputs explicit (direction can't be nested)
            link("input", src)
            link("output", data)

        discover()                        # final gap-fill below the software component
```

Running `python ro-crate-metadata.py` writes `ro-crate-metadata.json`. The
example shows both construction paths: `person`/`variable` built ad hoc inside a
`link(...)` call, and bound (`ada`, `velocity`) for reuse — with `velocity`
entered via `with` to set its own metadata before linking. Containment
(`software`, `dataset`, `file`) nests implicitly via `hasPart`; every other
relationship is an explicit `link`.

---

## Dependencies

- `rocrate` (rocrate-py) — RO-Crate construction and serialisation
- `cffconvert` — `CITATION.cff` parsing
- `csvw` — CSVW metadata parsing
- `frictionless` — Frictionless Data Package / Table Schema parsing
- `pathspec` — Git wildmatch (`.gitignore`) semantics

Avoid additional dependencies unless necessary. The implementation should remain
small and hackable.

---

## Scope

Implement enough to demonstrate convention discovery, metadata merging, reusable
entities, fragment annotation, and RO-Crate generation, across:

- entities: `software`, `dataset`, `file`, `person`, `variable`, `workflow`
- selection & operations: `select`, `merge`, `discover`, `role`, `link`
- conventions: `CITATION.cff`, `pyproject.toml`, `package.json`, CSVW,
  Frictionless Data, `README` / `LICENSE`

Avoid: advanced profile support, complex validation, global reasoning,
optimisation, plugin systems, configuration systems, and any command-line tool.

The proof-of-concept should remain small, understandable, and hackable.
