"""Convention handler registration and built-in metadata conventions."""

import json
import tomllib

HANDLERS = []


def convention(fn):
    """Register a convention handler, giving newer handlers precedence."""

    HANDLERS.insert(0, fn)
    return fn


def try_merge(path, context):
    """Try convention handlers in precedence order."""

    return any(handler(path, context) for handler in HANDLERS)


def _set_missing(entity, prop, value):
    if value not in (None, "", [], {}) and entity.get(prop) is None:
        entity[prop] = value


def _directory_context(path, context, kind):
    return context.builder.resolve_directory(path.parent, kind, context)


def _data_context(path, context):
    return context.builder.resolve_path(path, "file", context)


def _concept_key(prefix, path, *parts):
    suffix = ":".join(str(part) for part in parts)
    return f"{prefix}:{path.resolve()}:{suffix}"


@convention
def license_handler(path, context):
    name = path.name.lower()
    if not (
        name in {"license", "licence"}
        or name.startswith("license.")
        or name.startswith("licence.")
    ):
        return False
    target = context.builder.paths.get(
        context.builder.normalize(str(path.parent.relative_to(context.builder.root)))
    ) or context
    _set_missing(target.entity, "license", path.read_text(encoding="utf-8").strip())
    return True


@convention
def readme_handler(path, context):
    name = path.name.lower()
    if name != "readme" and not name.startswith("readme."):
        return False
    target = context.builder.paths.get(
        context.builder.normalize(str(path.parent.relative_to(context.builder.root)))
    ) or context
    _set_missing(target.entity, "description", path.read_text(encoding="utf-8").strip())
    return True


@convention
def pyproject_handler(path, context):
    if path.name.lower() != "pyproject.toml":
        return False
    target = _directory_context(path, context, "software")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    poetry = data.get("tool", {}).get("poetry", {})
    source = project or poetry
    for key, prop in (
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("keywords", "keywords"),
    ):
        _set_missing(target.entity, prop, source.get(key))
    license_value = source.get("license")
    if isinstance(license_value, dict):
        license_value = license_value.get("text") or license_value.get("file")
    _set_missing(target.entity, "license", license_value)
    _set_missing(target.entity, "programmingLanguage", "Python")
    return True


@convention
def package_json_handler(path, context):
    if path.name.lower() != "package.json":
        return False
    target = _directory_context(path, context, "software")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, prop in (
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("keywords", "keywords"),
        ("license", "license"),
        ("homepage", "url"),
    ):
        _set_missing(target.entity, prop, data.get(key))
    _set_missing(target.entity, "programmingLanguage", "JavaScript")
    return True


@convention
def citation_handler(path, context):
    if path.name.lower() != "citation.cff":
        return False
    from cffconvert import Citation

    data = Citation(path.read_text(encoding="utf-8")).cffobj
    kind = "dataset" if data.get("type") == "dataset" else "software"
    target = _directory_context(path, context, kind)
    builder = target.builder
    for key, prop in (
        ("title", "name"),
        ("version", "version"),
        ("abstract", "description"),
        ("keywords", "keywords"),
        ("license", "license"),
        ("repository-code", "codeRepository"),
        ("url", "url"),
    ):
        _set_missing(target.entity, prop, data.get(key))
    for index, author in enumerate(data.get("authors", [])):
        full_name = " ".join(
            part for part in (author.get("given-names"), author.get("family-names")) if part
        ) or author.get("name", "Unknown")
        properties = {}
        if author.get("orcid"):
            properties["identifier"] = author["orcid"]
        if author.get("email"):
            properties["email"] = author["email"]
        person = builder.derived_concept(
            _concept_key("cff", path, index), "person", full_name, properties
        )
        builder.append_unique(target.entity, "author", person.entity)
    return True


@convention
def datapackage_handler(path, context):
    if path.name.lower() != "datapackage.json":
        return False

    from frictionless import Package

    try:
        package = Package(path)
    except Exception:
        return False
    target = _directory_context(path, context, "dataset")
    builder = target.builder

    for value, prop in (
        (package.name, "name"),
        (package.title, "alternateName"),
        (package.description, "description"),
        (package.version, "version"),
        (package.licenses, "license"),
    ):
        _set_missing(target.entity, prop, value)

    for resource_index, resource in enumerate(package.resources):
        resource_path = getattr(resource, "path", None)
        if not isinstance(resource_path, str):
            continue
        full_path = (path.parent / resource_path).resolve()
        if not full_path.is_file():
            continue
        try:
            full_path.relative_to(builder.root)
        except ValueError:
            continue
        file_node = builder.resolve_path(full_path, "file", target)

        for value, prop in (
            (resource.title, "name"),
            (resource.name, "alternateName"),
            (resource.description, "description"),
            (resource.format, "encodingFormat"),
            (resource.mediatype, "encodingFormat"),
        ):
            _set_missing(file_node.entity, prop, value)

        schema = getattr(resource, "schema", None)
        for field_index, field in enumerate(getattr(schema, "fields", ())):
            field_name = field.name or field.title
            if not field_name:
                continue
            properties = {
                "alternateName": field.title,
                "description": field.description,
                "valueType": field.type,
            }
            variable = builder.derived_concept(
                _concept_key("frictionless", path, resource_index, field_index),
                "variable",
                str(field_name),
                {key: value for key, value in properties.items() if value},
            )
            fragment = builder.fragment(file_node, f"column:{field_name}")
            builder.append_unique(
                fragment.entity, "variableMeasured", variable.entity
            )
    return True


@convention
def csvw_handler(path, context):
    name = path.name.lower()
    if not (name == "csv-metadata.json" or name.endswith("-metadata.json")):
        return False
    from csvw.metadata import TableGroup

    try:
        group = TableGroup.from_file(path)
    except Exception:
        return False
    tables = list(group.tables)
    if not tables and getattr(group, "url", None):
        tables = [group]
    handled = False
    for table_index, table in enumerate(tables):
        csv_path = (path.parent / str(table.url)).resolve()
        if not csv_path.is_file():
            continue
        try:
            csv_path.relative_to(context.builder.root)
        except ValueError:
            continue
        target = _data_context(csv_path, context)
        target.entity["encodingFormat"] = "text/csv"
        schema = getattr(table, "tableSchema", None)
        for column_index, column in enumerate(getattr(schema, "columns", ())):
            if column.virtual:
                continue
            properties = {}
            if column.titles:
                titles = column.titles
                if isinstance(titles, dict):
                    titles = next(iter(titles.values()), None)
                if isinstance(titles, (list, tuple)):
                    titles = titles[0] if titles else None
                if titles:
                    properties["description"] = str(titles)
            datatype = getattr(column, "datatype", None)
            if datatype is not None:
                properties["valueType"] = str(getattr(datatype, "base", datatype))
            variable = context.builder.derived_concept(
                _concept_key("csvw", path, table_index, column_index),
                "variable",
                str(column.name),
                properties,
            )
            fragment = context.builder.fragment(target, f"column:{column.name}")
            context.builder.append_unique(
                fragment.entity, "variableMeasured", variable.entity
            )
        handled = True
    return handled
