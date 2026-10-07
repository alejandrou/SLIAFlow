# Building and running the genuine UC2 blood-vessel enhancement locally

This describes how the vendored UC2 component is compiled and run on this
machine, and what was measured when it was. Nothing in
`workspace/components/blood_vessels_enhancement` is modified: the sources are
staged, patched, built and run under `build\uc2\`, and every build re-checks
that the vendored copy is untouched and that the staged sources are that copy
plus the versioned patches. The patches and their results are recorded in
[`uc2_changes.md`](uc2_changes.md).

Since `SLIA-021` SLIAFlow runs UC2 itself on every Capture, on IUMA's
calibrated LCTF cube `input\002-04` (`extensions\SLIAFlow\README.md`). The
enhancement is the vendored C code doing real work. Only the acquisition is
simulated, so the map carries `simulated` with the detail
`real UC2 blood-vessel enhancement, recorded IUMA LCTF capture 002-04, calibrated
by IUMA (simulated acquisition)`. It is a visual enhancement, not a quantitative
map and not a clinical result.

## Build

```powershell
.\scripts\development\build-uc2.ps1 -Clean
```

What the script does, in order:

1. Checks the vendored copy through its own Git repository. The outer repository
   ignores `/workspace/`, so `git status` from the project root says nothing
   about it. The copy must be at partner commit `1b5e9ae` with no tracked file
   modified. `CODE_REVIEW.md` is untracked there and expected.
2. Copies the 13 C sources and headers into `build\uc2\source\`.
3. Applies the patches in `scripts\development\uc2-patches\`, in name order
   (`uc2_changes.md`).
4. Compiles there:

   ```text
   C:\msys64\usr\bin\gcc.exe -Wall -O3 -g main.c params.c functions.c hdr_reader.c BV_enhancement.c png_writer.c -lm -o uc2_bvmap.exe
   ```

5. Copies `msys-2.0.dll` beside the binary.
6. Fails unless the compiler printed exactly the four expected warnings.
7. Fails unless every staged source equals, by SHA-256, its vendored original
   plus the patches, rebuilt from scratch in `build\uc2\expected\`.

### Toolchain

| Component | Value |
| --- | --- |
| Compiler | `gcc (GCC) 15.3.0`, MSYS2 `usr\bin`, target `x86_64-pc-cygwin` |
| Runtime | `msys-2.0.dll`, copied from `C:\msys64\usr\bin` |

The compiler is the MSYS2 POSIX-layer GCC, **not** the UCRT64 one.
`hdr_reader.c` calls `getline`, which the Windows C runtime does not provide.
UCRT64 GCC 16.2.0 stops with `implicit declaration of function 'getline'`, which
GCC 14 and later treat as an error. The `main.out` that first ran UC2 on this
machine was built the same way: it reports `GCC: (GNU) 15.3.0` and imports
`msys-2.0.dll`.

`cc1` loads its DLLs from PATH. Run from Git Bash, whose own MSYS runtime comes
first on PATH, it fails with `error while loading shared libraries`. The script
puts `C:\msys64\usr\bin` first for the compile only.

The compile line is the vendored README's minus `logger.h`. Naming a header on
the command line makes GCC write `logger.h.gch`; `main.c` includes the header
anyway.

### Expected warnings

| Location | Flag | Why |
| --- | --- | --- |
| `main.c:196` | `-Wunused-variable` | The `default:` branch, taken for any data type other than 12 or 4, computes `BVMap` and never writes it. Line 167 before patch 0002 |
| `hdr_reader.c:50`, `:102`, `:109` | `-Wchar-subscripts` | `isdigit` called with a `char` |

They are not silenced and the source is not edited to remove them.

### Measured

| Item | 2026-09-16, no patch | 2026-10-05, patches 0001 and 0002 |
| --- | --- | --- |
| Binary | 413,364 bytes | 417,718 bytes |
| SHA-256 | `8A9D192C...958C321` | Varied across clean builds: `B93EE364...`, `E398B649...` |
| Vendored copy | `1b5e9ae`, 0 tracked changes, untracked `CODE_REVIEW.md` | the same |

The binary's hash depends on the build directory, because `-g` embeds source
paths. It also varied across two clean builds in the same directory on
2026-10-05, with the same size, staged sources, compiler warnings and checked
PNG outputs. The binary hash is therefore recorded as an observation, not an
acceptance oracle.

## How SLIAFlow runs it

On Capture, `SLIAFlowUc2Run.py` starts `build\uc2\source\uc2_bvmap.exe` with
one argument, the cube's folder in forward slashes (`C:/.../input/002-04`), and
`build\uc2\run\` as its working directory, as a background `QProcess` with no
shell and a 30 s timeout, holding `build\uc2\.uc2-runner.lock`. UC2 wrote
`002-04-BVMap.png` (1080 x 1080) in 0.2 to 0.35 s.

Before the process starts: the cube is described again and must be unchanged
since Capture; its files must be `LCTF_Calibrated_Cube_Single.hdr` and `.dat`;
its bands 4, 16 and 50 must be 480, 540 and 710 nm within 0.01 nm; the binary
and `msys-2.0.dll` must be staged; the paths must fit UC2's buffers (511
characters for the input, 255 for the output). After it: a non-zero exit, a
crash, a timeout, any of UC2's error lines on either stream whatever the exit
code, or a missing, stale, undecodable or wrongly sized PNG fails the run. A
failed or refused UC2 run never fails UC1's.
