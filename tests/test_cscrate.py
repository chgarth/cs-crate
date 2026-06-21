import json
from pathlib import Path

from cscrate import (
    convention,
    crate,
    dataset,
    discover,
    file,
    link,
    merge,
    person,
    select,
    software,
    variable,
    workflow,
)


def graph(root):
    return {
        item["@id"]: item
        for item in json.loads((root / "ro-crate-metadata.json").read_text())["@graph"]
    }


def ids(value):
    values = value if isinstance(value, list) else [value]
    return [item["@id"] for item in values]


def test_core_dsl_and_determinism(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.vtk").write_text("a")
    (tmp_path / "data" / "b.vtk").write_text("b")

    def generate():
        with crate(str(tmp_path)):
            with software("."):
                ada = person("Ada Lovelace")
                link("author", ada)
                velocity = variable("velocity", unit="m/s")
                with dataset("data") as data:
                    link("variableMeasured", velocity)
                    file("data/a.vtk")
                    with select("data/*.vtk#point-data:velocity"):
                        link("variableMeasured", velocity)
                with workflow("benchmark"):
                    link("output", data)

    generate()
    first = (tmp_path / "ro-crate-metadata.json").read_bytes()
    generate()
    assert (tmp_path / "ro-crate-metadata.json").read_bytes() == first

    data = graph(tmp_path)
    assert {"Dataset", "SoftwareSourceCode"} <= set(data["./"]["@type"])
    assert "data/" in ids(data["./"]["hasPart"])
    assert "data/a.vtk" in ids(data["data/"]["hasPart"])
    assert data["#velocity"]["unitText"] == "m/s"
    fragment = data["data/a.vtk#point-data:velocity"]
    assert "@type" not in fragment
    assert ids(fragment["isPartOf"]) == ["data/a.vtk"]
    assert ids(fragment["variableMeasured"]) == ["#velocity"]
    assert "data/a.vtk#point-data:velocity" not in ids(data["./"]["hasPart"])


def test_merges_and_discovery(tmp_path):
    (tmp_path / "README.md").write_text("A useful package")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="1.2.3"\ndescription="Demo project"\n'
    )
    component = tmp_path / "nested" / "web"
    component.mkdir(parents=True)
    (component / "package.json").write_text(
        '{"name":"web","version":"2.0.0","description":"UI"}'
    )
    ignored = tmp_path / "node_modules" / "x"
    ignored.mkdir(parents=True)
    (ignored / "package.json").write_text('{"name":"ignored"}')

    with crate(str(tmp_path)):
        with software("."):
            discover()

    data = graph(tmp_path)
    assert data["./"]["name"] == "demo"
    assert data["./"]["description"] == "Demo project"
    assert data["nested/web/"]["name"] == "web"
    assert "nested/" in data
    assert "node_modules/x/" not in data


def test_csvw_and_frictionless(tmp_path):
    (tmp_path / "table.csv").write_text("speed\n1\n")
    (tmp_path / "table-metadata.json").write_text(
        json.dumps(
            {
                "@context": "http://www.w3.org/ns/csvw",
                "url": "table.csv",
                "tableSchema": {
                    "columns": [{"name": "speed", "datatype": "number"}]
                },
            }
        )
    )
    survey = tmp_path / "survey"
    survey.mkdir()
    (survey / "responses.csv").write_text("age\n20\n")
    (survey / "datapackage.json").write_text(
        json.dumps(
            {
                "name": "survey",
                "resources": [
                    {
                        "name": "responses",
                        "path": "responses.csv",
                        "schema": {"fields": [{"name": "age", "type": "integer"}]},
                    }
                ],
            }
        )
    )

    with crate(str(tmp_path)):
        with dataset("."):
            with file("table.csv"):
                merge("table-metadata.json")
            with dataset("survey"):
                merge("survey/datapackage.json")

    data = graph(tmp_path)
    assert "variableMeasured" not in data["table.csv"]
    csv_fragment = data["table.csv#column:speed"]
    assert "@type" not in csv_fragment
    assert ids(csv_fragment["variableMeasured"]) == ["#speed"]
    assert ids(csv_fragment["isPartOf"]) == ["table.csv"]
    assert "variableMeasured" not in data["survey/responses.csv"]
    field_fragment = data["survey/responses.csv#column:age"]
    assert "@type" not in field_fragment
    assert ids(field_fragment["variableMeasured"]) == ["#age"]
    assert ids(field_fragment["isPartOf"]) == ["survey/responses.csv"]
    assert "survey/responses.csv" in ids(data["survey/"]["hasPart"])
    assert "table.csv#column:speed" not in ids(data["./"]["hasPart"])
    assert "survey/responses.csv#column:age" not in ids(data["./"]["hasPart"])


def test_citation_cff(tmp_path):
    (tmp_path / "CITATION.cff").write_text(
        "\n".join(
            [
                "cff-version: 1.2.0",
                "title: Example",
                "message: Cite this",
                "type: software",
                "license: MIT",
                "authors:",
                "  - given-names: Ada",
                "    family-names: Lovelace",
            ]
        )
    )

    with crate(str(tmp_path)):
        with software("."):
            merge("CITATION.cff")
            merge("CITATION.cff")

    data = graph(tmp_path)
    assert data["./"]["name"] == "Example"
    assert data["./"]["author"] == [{"@id": "#ada-lovelace"}]
    assert "#ada-lovelace-2" not in data


def test_hidden_paths_and_discovery_scope_boundary(tmp_path):
    component = tmp_path / "component"
    component.mkdir()
    (component / "package.json").write_text(
        '{"name":"declared-component","description":"local metadata"}'
    )
    (component / "nested").mkdir()
    (component / "nested" / "package.json").write_text('{"name":"must-not-discover"}')
    (tmp_path / ".metadata").write_text("hidden")

    with crate(str(tmp_path)):
        with software("."):
            software("component")
            file(".metadata")
            discover()

    data = graph(tmp_path)
    assert data["component/"]["name"] == "declared-component"
    assert "component/nested/" not in data
    assert ".metadata" in data


def test_discovery_consumes_metadata_without_emitting_unreferenced_files(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\n')
    (tmp_path / "payload.txt").write_text("data")

    with crate(str(tmp_path)):
        with software("."):
            discover()

    data = graph(tmp_path)
    assert "pyproject.toml" not in data
    assert "payload.txt" not in data


def test_debug_output_reports_merges_without_unreferenced_entities(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\n')
    (tmp_path / "payload.txt").write_text("data")

    with crate(str(tmp_path)):
        with software("."):
            merge("pyproject.toml")
            discover()

    output = capsys.readouterr().out.splitlines()
    assert "from pyproject.toml: merged metadata" in output
    assert not any("payload.txt" in line for line in output)


def test_user_convention_overrides_builtins(tmp_path):
    (tmp_path / "README.md").write_text("built-in description")

    @convention
    def custom_readme(path, context):
        if path.name != "README.md":
            return False
        context["name"] = "handled by user"
        return True

    try:
        with crate(str(tmp_path)):
            with dataset("."):
                merge("README.md")
    finally:
        from cscrate.conventions import HANDLERS

        HANDLERS.remove(custom_readme)

    data = graph(tmp_path)
    assert data["./"]["name"] == "handled by user"
    assert "description" not in data["./"]


def test_paired_handlers_skip_missing_resources(tmp_path):
    (tmp_path / "missing-metadata.json").write_text(
        json.dumps(
            {
                "@context": "http://www.w3.org/ns/csvw",
                "url": "missing.csv",
                "tableSchema": {"columns": [{"name": "value"}]},
            }
        )
    )

    with crate(str(tmp_path)):
        with dataset("."):
            discover()

    data = graph(tmp_path)
    assert "missing.csv" not in data
    assert "missing-metadata.json" not in data


def test_discovery_consumes_csvw_descriptor(tmp_path):
    (tmp_path / "table.csv").write_text("speed\n1\n")
    (tmp_path / "table-metadata.json").write_text(
        json.dumps(
            {
                "@context": "http://www.w3.org/ns/csvw",
                "url": "table.csv",
                "tableSchema": {"columns": [{"name": "speed"}]},
            }
        )
    )

    with crate(str(tmp_path)):
        with dataset("."):
            discover()

    data = graph(tmp_path)
    assert "table-metadata.json" not in data
    assert "variableMeasured" not in data["table.csv"]
    assert ids(data["table.csv#column:speed"]["variableMeasured"]) == ["#speed"]


def test_plain_file_selection_annotates_files(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "run1.vtk").write_text("one")
    (results / "run2.vtk").write_text("two")

    with crate(str(tmp_path)):
        with dataset("."):
            with select("results/*.vtk"):
                link("author", person("Jane Roe"))

    data = graph(tmp_path)
    for name in ("run1.vtk", "run2.vtk"):
        selected = data[f"results/{name}"]
        assert selected["@type"] == "File"
        assert ids(selected["author"]) == ["#jane-roe"]


def test_fragment_selection_is_untyped_reused_and_not_containment(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "run1.vtk").write_text("one")

    with crate(str(tmp_path)):
        with dataset("."):
            velocity = variable("velocity", unit="m/s")
            with select("results/*.vtk#point-data:velocity"):
                link("variableMeasured", velocity)
            with select("results/*.vtk#point-data:velocity"):
                link("variableMeasured", velocity)

    metadata = json.loads((tmp_path / "ro-crate-metadata.json").read_text())
    data = {item["@id"]: item for item in metadata["@graph"]}
    fragment_id = "results/run1.vtk#point-data:velocity"
    fragment = data[fragment_id]
    assert "@type" not in fragment
    assert ids(fragment["isPartOf"]) == ["results/run1.vtk"]
    assert ids(fragment["variableMeasured"]) == ["#velocity"]
    assert data["#velocity"]["unitText"] == "m/s"
    assert fragment_id not in ids(data["./"]["hasPart"])
    assert fragment_id not in ids(data["results/run1.vtk"].get("hasPart", []))
    assert sum(item["@id"] == fragment_id for item in metadata["@graph"]) == 1
