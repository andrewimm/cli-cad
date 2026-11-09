# Slicer compatibility check

`check.py` exports a small test set from the bundled examples and loads each file in every slicer it finds.
It then compares what each slicer understood with what cad meant:
- every part is present;
- each part is the right size;
- each part is in the right place relative to the rest of the model;
- each part is on the right extruder.

With PrusaSlicer it also slices to G-code and checks which extruders the print uses.

| fixture | why |
|---|---|
| `plate_with_holes`, objects | one part |
| `multimaterial_case`, objects | six parts in three materials, as separate objects |
| `multimaterial_case`, multimaterial | an assembly whose parts sit at different heights (a case on its feet) |
| `nameplate`, multimaterial | a badge sitting on top of a plate |
| both multimaterial, `--3mf-for prusa` | PrusaSlicer's own layout |

Slicing is skipped, with a note, for separate-objects files whose parts overlap on the bed:
`multimaterial_case`'s feet sit under the case, and PrusaSlicer refuses those as G-code path conflicts.

Known limitations are reported as `know`, not as failures. Example: PrusaSlicer splits the default
multimaterial layout into separate objects. If a known limitation stops reproducing, the check fails, so
the table in `cad docs 3mf` stays true.

## Run it

**In an ephemeral Vercel sandbox** (Linux, nothing installed locally; needs the `sandbox` CLI, logged in):

```bash
scripts/slicer_compat/sandbox.sh --save            # first time: provisions (~15 min) and prints a snapshot id
scripts/slicer_compat/sandbox.sh --snapshot <id>   # later runs, from that snapshot (~5 min)
```

It uploads this working tree, uncommitted changes included, and builds and installs cad. It then runs the
check against PrusaSlicer, OrcaSlicer and Cura and writes `slicer-compat-report.txt` / `.json`. The sandbox
is removed afterwards. Hobby plans cap a sandbox at 45 minutes.

**On any Ubuntu 26.04 x86_64 machine:** run `setup.sh` once, then:

```bash
source ~/slicers/env.sh
python scripts/slicer_compat/check.py --require prusa,orca,cura
```

**Locally against Bambu Studio** (macOS or Linux, Bambu Studio installed), with a development build on PATH:

```bash
PATH="$PWD/target/release:$PATH" uv run python scripts/slicer_compat/check.py --require bambu
```

## How each slicer is read

| slicer | how | what is not covered |
|---|---|---|
| PrusaSlicer (apt package) | `--export-3mf` re-save, then its `Slic3r_PE_model.config` is read; `--export-gcode` | — |
| OrcaSlicer (unpacked Linux AppImage) | `--export-3mf` re-save, then its `model_settings.config` is read | slicing; its 2.5 profiles are packed, so `cad slice` cannot drive it yet |
| Cura (unpacked Linux AppImage) | Cura's own 3MF parser (pySavitar) on the file; its reader then sets each object's extruder from `extruder_nr` | the desktop app itself, and slicing |
| Bambu Studio | `--export-3mf` re-save, as in `tests/test_bambu.py` | — |

The OrcaSlicer AppImage links FFmpeg 7, which Ubuntu 26.04 no longer ships. `setup.sh` installs it from
25.04 instead, pinned low. The OrcaSlicer flatpak cannot be installed in the sandbox, because it needs a
session bus and FUSE.
