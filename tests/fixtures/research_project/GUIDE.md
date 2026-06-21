# Reading the generated crate

After running `ro-crate-metadata.py`, inspect `ro-crate-metadata.json`.

Look for:

1. `./` carrying both `Dataset` and `SoftwareSourceCode` types.
2. `src/` and `data/` linked through `hasPart`.
3. CSV columns represented as `PropertyValue` entities.
4. VTK fragments linked to the shared `#velocity` variable.
5. `#benchmark` referencing `src/` as input and `data/` as output.

