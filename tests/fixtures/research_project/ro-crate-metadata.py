#!/usr/bin/env python3
"""Generate the RO-Crate for this educational fixture repository."""

from cscrate import *


with crate("."):
    # Declaring software(".") gives the crate root software semantics.
    with software(".") as project:
        project.append_to("keywords", "fluid dynamics")
        role("research software")

        # These metadata files enrich the software entity.
        merge("pyproject.toml")
        merge("CITATION.cff")
        link("contributor", person("Research Team"))

        # Route 1: file(...) explicitly creates a File entity because we want
        # to describe and refer to this particular file.
        with file("GUIDE.md") as guide:
            guide["description"] = "How to inspect the generated crate"

        with software("src") as source:
            with file("src/solver.py") as solver:
                solver["programmingLanguage"] = "Python"
            discover()

        with dataset("data") as data:
            temperature = variable("temperature", unit="K")
            velocity = variable("velocity", unit="m/s")
            link("variableMeasured", temperature)
            link("variableMeasured", velocity)

            # Route 2: convention descriptors create the files they reference.
            merge("data/measurements-metadata.json")

            with dataset("data/survey"):
                merge("data/survey/datapackage.json")

            # Route 3: select(...) creates matching files and fragments because
            # the graph needs entities to carry the fragment annotations.
            with select("data/results/*.vtk#point-data:velocity"):
                link("about", velocity)

            discover()

        with workflow("benchmark"):
            link("input", source)
            link("output", data)

        # Discovery enriches known entities but leaves unrelated ordinary files
        # such as src/config.json implicit.
        discover()
