# Which IUMA captures run through UC1 and UC2

SLIAFlow offers every capture in `input/` under **Recorded capture**
(`ADR-0006`), including any that does not run. This page records, per capture,
whether UC1 and UC2 run on it, and for each failure why and what could fix it.
It names captures by ID only and holds no image or pixel data
(`.ai/policies/medical-data-policy.md`).

## How to check

After `build-uc1.ps1` and `build-uc2.ps1`:

```powershell
.\.venv\Scripts\python.exe scripts\development\check-captures.py
.\.venv\Scripts\python.exe scripts\development\check-captures.py --capture S-N-005-01
```

Without `--capture` it checks every capture SLIAFlow would list, so a capture
added to `input/` is checked by running it again. `--input DIR` checks the
captures of another folder laid out like `input/`, for example a delivery
before it is copied in. It prints the table below, and exits 1 if any
capture fails a step. Only a run over every capture in `input/` writes the
table to `build/captures/compatibility.md`; a run with `--capture` or another
`--input` leaves it as it was. A capture that cannot be read fails its row with
the reason, and the others are still checked. It needs about 11 s per capture and holds both runner locks, so
do not press Capture in SLIAFlow while it runs.

Each capture goes through four steps:

| Step | PASS means |
| --- | --- |
| Cube | SLIAFlow's own checks accept the cube: its header path is under 260 characters, its ID is ASCII, UC1's paths for it are under 128 characters, the header and data agree (float32, BSQ, byte order 0, no header offset, size), the wavelengths are in nanometres, one number per band, and they are the LCTF grid, 109 bands at 460-1000 nm, that UC1's band mapping is defined for (`ADR-0004` decisions 4 and 6). The check makes the module's own checks on Capture (`loadCalibratedCube`, `describeUc1Input`, `assertUc1PathsFit`), so a FAIL here is a capture SLIAFlow refuses before freezing LiveView, with the same reason |
| UC1 | SLIAFlow's own writer maps the cube onto UC1's 93 bands, re-reading it before and after the copy as before a run (`writeUc1Input`); what it wrote is byte for byte the mapping `uc_oracles.py` restates from the cube's header; and UC1, given it, exits 0 within SLIAFlow's 60 s timeout and writes its six images at the cube's size |
| UC1 oracles | `CalibratedImage_BIP.bmp` is byte for byte the image predicted from the cube, and `pca.bmp` is within one grey level of NumPy's first principal component |
| UC2 | SLIAFlow's own checks before a UC2 run pass (file names, patch 0002's fixed bands at 480, 540 and 710 nm, path lengths), and UC2 writes its map, under the name SLIAFlow looks for, at the cube's size within SLIAFlow's 30 s timeout, pixel-identical to a NumPy replica of its steps |

**PASS says nothing about accuracy.** It means the pipelines ran and agree
with an independent recomputation. UC1's model was trained on another camera,
so its classes on these cubes show what the pipeline does, not whether it is
right (`ADR-0004` decision 5). No capture has a labelling to compare with.
K-means outputs vary from run to run, so only their size is checked; the
recorded hashes of one cube stay with `check-uc1.py` and `check-uc2.py`.

## Result, 2026-10-09

Checked 2026-10-09 with scripts/development/check-captures.py: 16 of 16 captures pass every step.

| Capture | Lines x samples | Cube | UC1 | UC1 oracles | UC2 | UC1 s | UC2 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-N-002-01 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.8 | 0.3 |
| S-N-002-02 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.5 | 0.3 |
| S-N-002-03 | 1080 x 1301 | PASS | PASS | PASS (99.98% of pca.bmp exact) | PASS | 2.3 | 0.3 |
| S-N-002-04 | 1080 x 1080 | PASS | PASS | PASS (99.97% of pca.bmp exact) | PASS | 2.0 | 0.3 |
| S-N-003-01 | 1080 x 1080 | PASS | PASS | PASS (99.97% of pca.bmp exact) | PASS | 2.0 | 0.2 |
| S-N-003-02 | 1080 x 1301 | PASS | PASS | PASS (99.98% of pca.bmp exact) | PASS | 2.5 | 0.3 |
| S-N-003-03 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.5 | 0.2 |
| S-N-005-01 | 1080 x 1301 | PASS | PASS | PASS (99.98% of pca.bmp exact) | PASS | 2.4 | 0.3 |
| S-N-005-02 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.3 | 0.3 |
| S-N-005-03 | 1080 x 1301 | PASS | PASS | PASS (100.00% of pca.bmp exact) | PASS | 2.5 | 0.3 |
| S-N-006-01 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.6 | 0.3 |
| S-N-006-02 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.4 | 0.3 |
| S-N-006-03 | 1080 x 1301 | PASS | PASS | PASS (99.94% of pca.bmp exact) | PASS | 2.3 | 0.3 |
| S-N-007-01 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.6 | 0.3 |
| S-N-007-02 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.5 | 0.2 |
| S-N-007-03 | 1080 x 1301 | PASS | PASS | PASS (99.99% of pca.bmp exact) | PASS | 2.4 | 0.2 |

The times are the UC1 and UC2 processes alone, on this laptop, one run each.
The 1080 x 1301 cubes, 20 % more pixels than 1080 x 1080, took UC1 2.3 to
2.8 s against 2.0 s, well inside the 60 s timeout. `S-N-002-04` is the cube
recorded as `002-04` until 2026-10-08, byte for byte.

The first check, on 2026-10-08, also passed 16 of 16, with UC1 1.9 to 3.5 s.
Its UC1 step ran on a mapped cube the checker wrote itself; since 2026-10-09
the step runs on the cube SLIAFlow's writer maps and compares it with the
independent mapping.

## Failures and possible fixes

None on 2026-10-09 or 2026-10-08. If a capture added later fails, the step that fails points
to the cause:

| Step fails | Likely cause | Possible fix |
| --- | --- | --- |
| Cube: the ID has characters other than ASCII | A folder named with accents or other letters | Rename the folder in `input/` with ASCII letters, digits and dashes; UC1's header and the paths UC1 and UC2 are given are built from the ID |
| Cube: the path is 260 characters or more | A very long ID, nested twice, or `input/` deep in the disk | Shorten the ID or move the repository to a shorter path; Slicer's Python does not open longer paths |
| Cube: a UC1 path is 128 characters or more | An ID of 89 characters or more with the repository at `C:\stratum`: UC1 reads `build/uc1/UC1/input/<ID>/raw.dat` | Shorten the ID or move the repository; UC1 keeps at most 127 characters of a path and would truncate it silently |
| Cube: header and data disagree | An incomplete copy, or another data type or interleave | Copy the capture again from IUMA's delivery; ask IUMA for the calibrated float32 BSQ cube |
| Cube: wavelengths missing, not numbers, not one per band, or not in nanometres | A header edited by hand or written by another tool | Ask IUMA for the header as their calibration writes it; do not edit it here |
| Cube: not on the LCTF grid | Another filter range or step | The band mapping is defined for this grid only (`ADR-0004` decision 4); another grid needs a new mapping, decided by the owner in a new ADR |
| UC1: SLIAFlow's mapped cube is not the expected mapping | A change to `SLIAFlowUc1Input`'s writer or band mapping | Compare the change with `ADR-0004` decision 4 and `uc1_changes.md`; the reason names the first band that differs. Change the writer, not the oracle, unless the mapping itself was decided again in an ADR |
| UC1: timeout or nonzero exit | GPU memory on a much larger cube, or a driver fault | `uc1_performance.md` gives this laptop's size limit; a smaller or cropped cube, or the measured parameter changes there, decided by the owner |
| UC1 oracles | A changed UC1 build, GPU or driver | Rebuild with `build-uc1.ps1` and run `check-uc1.py`; record again only after review (`uc1_changes.md`) |
| UC2 | Other fixed bands, or other file names | UC2 reads bands 4, 16 and 50 and the names `LCTF_Calibrated_Cube_Single.*` (`uc2_changes.md`); a capture with other names needs them as delivered by IUMA |
