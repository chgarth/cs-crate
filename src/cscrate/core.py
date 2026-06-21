import contextvars
import glob
import re
import warnings
from pathlib import Path, PurePosixPath

import pathspec
from rocrate.model.contextentity import ContextEntity
from rocrate.model.dataset import Dataset
from rocrate.model.file import File
from rocrate.rocrate import ROCrate

from .conventions import try_merge

_builder = contextvars.ContextVar("cscrate_builder", default=None)


def _active():
    """Return the builder for the active crate context."""

    builder = _builder.get()
    if builder is None:
        raise RuntimeError("cscrate entities and operations must be used inside crate(...)")
    return builder


def _slug(value):
    """Convert a display name into a stable conceptual-entity ID fragment."""

    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "entity"


def _values(value):
    """Normalize a missing, scalar, or list property value to a list."""

    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _entity_id(value):
    """Unwrap a Node to its rocrate-py entity, leaving other values unchanged."""

    return value.entity if isinstance(value, Node) else value


class Node:
    """A context-manager handle forwarding access to a rocrate-py entity."""

    def __init__(self, builder, entity, containment=False, path=None):
        self.builder = builder
        self.entity = entity
        self.containment = containment
        self.path = path

    def __enter__(self):
        self.builder.push([self])
        return self

    def __exit__(self, exc_type, exc, tb):
        self.builder.pop()

    def __getitem__(self, key):
        return self.entity[key]

    def __setitem__(self, key, value):
        self.entity[key] = _entity_id(value)

    def __getattr__(self, name):
        return getattr(self.entity, name)

    def append_to(self, key, value):
        self.entity.append_to(key, _entity_id(value))


class CrateNode(Node):
    def __enter__(self):
        self._token = _builder.set(self.builder)
        self.builder.push([self])
        return self

    def __exit__(self, exc_type, exc, tb):
        self.builder.pop()
        try:
            if exc_type is None:
                self.builder.write()
        finally:
            _builder.reset(self._token)


class Selection:
    def __init__(self, builder, nodes):
        self.builder = builder
        self.nodes = list(nodes)

    def __enter__(self):
        self.builder.push(self.nodes)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.builder.pop()

    def __iter__(self):
        return iter(self.nodes)


class Builder:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.crate = ROCrate()
        self.stack = []
        self.paths = {}
        self.fragments = {}
        self.derived_concepts = {}
        self.declared_dirs = set()
        self.concept_ids = {}
        patterns = [
            ".git/",
            "__pycache__/",
            ".venv/",
            "node_modules/",
            "build/",
            "dist/",
        ]
        ignore_file = self.root / ".gitignore"
        if ignore_file.exists():
            patterns.extend(ignore_file.read_text(encoding="utf-8").splitlines())
        self.ignore_spec = pathspec.GitIgnoreSpec.from_lines(patterns)
        self.crate.root_dataset._jsonld.pop("datePublished", None)
        root_node = Node(self, self.crate.root_dataset, True, "./")
        self.paths["./"] = root_node
        self.crate_node = CrateNode(self, self.crate.root_dataset, True, "./")

    @property
    def current(self):
        if not self.stack:
            raise RuntimeError("operation requires an active entity context")
        return self.stack[-1]

    def push(self, nodes):
        self.stack.append(nodes)

    def pop(self):
        self.stack.pop()

    def normalize(self, path):
        raw = Path(path)
        if raw.is_absolute():
            try:
                raw = raw.relative_to(self.root)
            except ValueError as exc:
                raise ValueError(f"path is outside crate root: {path}") from exc
        text = PurePosixPath(raw.as_posix()).as_posix()
        if text in ("", "."):
            return "./"
        if text == ".." or text.startswith("../"):
            raise ValueError(f"path is outside crate root: {path}")
        return text[2:] if text.startswith("./") else text

    def path_node(self, path, kind, *, explicit=True, attach=True):
        identifier = self.normalize(path)
        is_dir = kind in {"software", "dataset"}
        crate_id = "./" if identifier == "./" else identifier + ("/" if is_dir else "")
        node = self.paths.get(identifier)
        if node is None:
            cls = Dataset if is_dir else File
            entity = cls(self.crate, source=None, dest_path=crate_id)
            self.crate.add(entity)
            node = Node(self, entity, True, identifier)
            self.paths[identifier] = node
        self.ensure_type(node.entity, self.kind_type(kind))
        if explicit and is_dir:
            self.declared_dirs.add(identifier)
        if attach and self.stack:
            for parent in self.current:
                if parent.containment and parent.entity is not node.entity:
                    self.append_unique(parent.entity, "hasPart", node.entity)
        return node

    def concept(self, kind, name, properties):
        base = _slug(name)
        count = self.concept_ids.get(base, 0) + 1
        self.concept_ids[base] = count
        identifier = f"#{base}" if count == 1 else f"#{base}-{count}"
        props = {"@type": self.kind_type(kind), "name": name}
        props.update(properties)
        entity = ContextEntity(self.crate, identifier, properties=props)
        self.crate.add(entity)
        return Node(self, entity)

    def derived_concept(self, key, kind, name, properties):
        node = self.derived_concepts.get(key)
        if node is None:
            node = self.concept(kind, name, properties)
            self.derived_concepts[key] = node
        else:
            for prop, value in properties.items():
                if value not in (None, "", [], {}) and node.entity.get(prop) is None:
                    node.entity[prop] = value
        return node

    @staticmethod
    def kind_type(kind):
        return {
            "software": "SoftwareSourceCode",
            "dataset": "Dataset",
            "file": "File",
            "person": "Person",
            "variable": "PropertyValue",
            "workflow": "ComputationalWorkflow",
            "fragment": "CreativeWork",
        }[kind]

    @staticmethod
    def ensure_type(entity, type_name):
        existing = _values(entity.get("@type"))
        if type_name not in existing:
            entity._jsonld["@type"] = existing + [type_name]

    @staticmethod
    def append_unique(entity, prop, value):
        current = _values(entity.get(prop))
        value_id = value.id if hasattr(value, "id") else value
        if not any((item.id if hasattr(item, "id") else item) == value_id for item in current):
            entity.append_to(prop, value)

    def write(self):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r".*should follow the pattern.*"
            )
            self.crate.write_detached(self.root / "ro-crate-metadata.json")

    def ignored(self, relative, is_dir):
        candidate = relative + ("/" if is_dir else "")
        return self.ignore_spec.match_file(candidate)

    def resolve_path(self, path, kind, parent):
        """Get or create a path entity relative to the crate, attached to parent."""

        relative = self.normalize(str(path.relative_to(self.root)))
        existing = self.paths.get(relative)
        if existing is not None:
            self.ensure_type(existing.entity, self.kind_type(kind))
            return existing
        old_stack = self.stack
        self.stack = [[parent]]
        try:
            return self.path_node(relative, kind, explicit=False)
        finally:
            self.stack = old_stack

    def resolve_directory(self, path, kind, context):
        """Resolve a marked directory, creating hierarchy anchors as needed."""

        relative = self.normalize(str(path.relative_to(self.root)))
        existing = self.paths.get(relative)
        if existing is not None:
            self.ensure_type(existing.entity, self.kind_type(kind))
            return existing

        context_path = context.path or "./"
        context_dir = self.root if context_path == "./" else self.root / context_path
        try:
            tail = path.relative_to(context_dir)
            parent = context
            current = context_dir
        except ValueError:
            parent = self.paths["./"]
            current = self.root
            tail = path.relative_to(self.root)

        parts = tail.parts
        for index, part in enumerate(parts):
            current /= part
            current_kind = kind if index == len(parts) - 1 else "dataset"
            parent = self.resolve_path(current, current_kind, parent)
        return parent


def crate(root="."):
    return Builder(root).crate_node


def software(path):
    return _active().path_node(path, "software")


def dataset(path):
    return _active().path_node(path, "dataset")


def file(path):
    return _active().path_node(path, "file")


def person(name, **properties):
    return _active().concept("person", name, properties)


def variable(name, unit=None, **properties):
    if unit is not None:
        properties["unitText"] = unit
    return _active().concept("variable", name, properties)


def workflow(name, **properties):
    return _active().concept("workflow", name, properties)


def role(value):
    for target in _active().current:
        target.entity["roleName"] = value


def link(property_name, target):
    builder = _active()
    for subject in builder.current:
        builder.append_unique(subject.entity, property_name, target.entity)


def select(pattern):
    builder = _active()
    if "#" in pattern:
        file_pattern, fragment = pattern.split("#", 1)
    else:
        file_pattern, fragment = pattern, None
    matches = sorted(
        p for p in glob.glob(str(builder.root / file_pattern), recursive=True) if Path(p).is_file()
    )
    nodes = []
    for match in matches:
        file_node = builder.path_node(str(Path(match).relative_to(builder.root)), "file")
        if fragment is None:
            nodes.append(file_node)
            continue
        fragment_id = f"{file_node.entity.id}#{fragment}"
        fragment_node = builder.fragments.get(fragment_id)
        if fragment_node is None:
            entity = ContextEntity(
                builder.crate,
                fragment_id,
                properties={"@type": Builder.kind_type("fragment")},
            )
            builder.crate.add(entity)
            fragment_node = Node(builder, entity)
            builder.fragments[fragment_id] = fragment_node
            builder.append_unique(file_node.entity, "hasPart", entity)
        nodes.append(fragment_node)
    return Selection(builder, nodes)


def merge(source):
    builder = _active()
    path = builder.root / builder.normalize(source)
    if not path.exists():
        raise FileNotFoundError(path)
    for target in builder.current:
        if not try_merge(path, target):
            raise ValueError(f"unsupported metadata convention: {path.name}")
        print(f"from {builder.normalize(path)}: merged metadata")


def discover():
    builder = _active()
    for target in list(builder.current):
        if target.path is None:
            continue
        start = builder.root if target.path == "./" else builder.root / target.path
        if not start.is_dir():
            continue
        _discover_dir(builder, target, start, is_root=True)


def _discover_dir(builder, target, directory, *, is_root):
    """Merge conventions and recursively materialize a filesystem directory."""

    relative = builder.normalize(str(directory.relative_to(builder.root)))
    scope_boundary = not is_root and relative in builder.declared_dirs
    entries = sorted(directory.iterdir(), key=lambda p: p.name)
    local_target = builder.paths.get(relative, target)

    for entry in reversed(entries):
        entry_rel = builder.normalize(str(entry.relative_to(builder.root)))
        if (
            entry.is_dir()
            or entry.name == "ro-crate-metadata.json"
            or builder.ignored(entry_rel, False)
        ):
            continue
        before = set(builder.paths)
        if try_merge(entry, local_target):
            for identifier in sorted(set(builder.paths) - before):
                print(
                    f"from {entry_rel}: created entity "
                    f"{builder.paths[identifier].entity.id}"
                )
            print(f"from {entry_rel}: merged metadata")

    if scope_boundary:
        return

    for entry in entries:
        entry_rel = builder.normalize(str(entry.relative_to(builder.root)))
        if builder.ignored(entry_rel, entry.is_dir()):
            continue
        if entry.is_dir():
            child = builder.paths.get(entry_rel)
            if child is None:
                child = builder.resolve_path(entry, "dataset", local_target)
            _discover_dir(builder, child, entry, is_root=False)
