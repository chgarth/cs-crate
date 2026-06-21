import json
import shutil
import subprocess
import sys
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "research_project"


def load_graph(root):
    metadata = json.loads((root / "ro-crate-metadata.json").read_text())
    return {entity["@id"]: entity for entity in metadata["@graph"]}


def referenced_ids(value):
    values = value if isinstance(value, list) else [value]
    return [item["@id"] for item in values]


def generate(root):
    """Run the fixture exactly as a user runs an authoring script."""

    subprocess.run(
        [sys.executable, "ro-crate-metadata.py"],
        cwd=root,
        check=True,
    )


def test_educational_repository_exercises_generator_features(tmp_path):
    """The fixture demonstrates the major authoring and discovery features."""

    project = tmp_path / "research-project"
    shutil.copytree(FIXTURE, project)

    generate(project)
    first_output = (project / "ro-crate-metadata.json").read_bytes()
    graph = load_graph(project)

    # The root is enriched by both explicit intent and conventional metadata.
    assert {"Dataset", "SoftwareSourceCode"} <= set(graph["./"]["@type"])
    assert graph["./"]["name"] == "flow-lab"
    assert graph["./"]["version"] == "1.0.0"
    assert graph["./"]["license"] == "CC0-1.0"
    assert "#grace-hopper" in referenced_ids(graph["./"]["author"])

    # Explicit contexts and file() calls create containment entities.
    assert "src/" in referenced_ids(graph["./"]["hasPart"])
    assert "data/" in referenced_ids(graph["./"]["hasPart"])
    assert "GUIDE.md" in referenced_ids(graph["./"]["hasPart"])
    assert "src/solver.py" in referenced_ids(graph["src/"]["hasPart"])
    assert graph["src/solver.py"]["programmingLanguage"] == "Python"

    # Metadata sources are consumed; explicitly referenced files remain.
    assert "pyproject.toml" not in graph
    assert "CITATION.cff" not in graph
    assert "data/measurements-metadata.json" not in graph
    assert "GUIDE.md" in graph
    assert "src/solver.py" in graph

    # This ordinary file is never referenced, so discovery leaves it implicit.
    assert "src/config.json" not in graph

    # Convention handlers create the data files described by their metadata.
    assert "data/measurements.csv" in graph
    assert "data/survey/responses.csv" in graph

    # CSVW columns and Frictionless fields create measured variables.
    csv_variables = referenced_ids(graph["data/measurements.csv"]["variableMeasured"])
    assert {"#time", "#temperature-2", "#velocity-2"} <= set(csv_variables)
    survey_variables = referenced_ids(
        graph["data/survey/responses.csv"]["variableMeasured"]
    )
    assert {"#participant", "#rating"} <= set(survey_variables)

    # Selection creates matching files and fragments, then links one variable.
    for run in ("run-01.vtk", "run-02.vtk"):
        assert f"data/results/{run}" in graph
        fragment = graph[f"data/results/{run}#point-data:velocity"]
        assert referenced_ids(fragment["about"]) == ["#velocity"]

    # Workflow links point to existing entities rather than string paths.
    workflow = graph["#benchmark"]
    assert referenced_ids(workflow["input"]) == ["src/"]
    assert referenced_ids(workflow["output"]) == ["data/"]

    # .gitignore rules are honored during discovery.
    assert "scratch/" not in graph
    assert "scratch/ignored.txt" not in graph

    # Re-running an unchanged authoring script is deterministic.
    generate(project)
    assert (project / "ro-crate-metadata.json").read_bytes() == first_output
