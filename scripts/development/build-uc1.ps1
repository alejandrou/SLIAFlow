<#
.SYNOPSIS
    Stage and build the vendored UC1 CUDA pipeline for this GPU.

.DESCRIPTION
    Copies the vendored `gpu_single_bsq/source/` and `svm_model/` trees into the
    already-ignored `build/uc1/UC1/`, applies the versioned patches in
    `scripts/development/uc1-patches/` to the staged source in name order,
    builds two binaries with the GUIDE section 3.1-B command lines retargeted at
    `sm_120`, and then asserts by SHA-256 that every staged file equals the
    `workspace/components/` original plus those patches (ADR-0004 decision 3).
    The vendored copy itself is never written to.

    - `stratum.opt.exe`, the release build, used by the standalone Python
      runner.
    - `stratum.opt.intermediate.exe`, the intermediate build
      (`-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT`), which SLIAFlow runs
      inside Slicer and whose per-stage BMPs it displays (SLIA-027, ADR-0003).

    Three things about this build are deliberate and must not be "fixed".

    The binary is never built or run in place. `main.cu` writes its output into
    the source tree it runs from, so building in `workspace/components/` would
    put generated files inside the vendored reference copy. Staging is
    mandatory, and the two-level layout is load-bearing: `main.cu` opens the
    SVM model as the literal relative path `../../svm_model/*.bin`.

    `nvcc` is invoked directly rather than through `make`. The Makefile's
    `FLAGS` carries the POSIX-only `-ldl`, which does not link on Windows.

    Each binary has its own list of expected compiler warnings, because the
    two command lines compile different code. They are not silenced and the
    vendored source is not edited to remove them. An absent expected warning is
    a surprise, and it is reported as one.

    Every change to UC1 is a patch, applied with `git apply`, which refuses a
    hunk whose context does not match instead of guessing. A patch that no
    longer applies, for example after a new UC1 delivery, fails the build; it
    is never skipped. What each patch does and what it produced is recorded in
    `docs/development/uc1_changes.md`.

.PARAMETER Clean
    Delete the staged build root before staging. Removes previous run outputs
    along with the binary.

.PARAMETER SkipBuild
    Stage, patch and run the hash assertion without invoking the compiler.

.PARAMETER PatchDirectory
    The folder of `*.patch` files to apply. Defaults to
    `scripts/development/uc1-patches`; another folder is only for checking how
    the script reacts to a patch that does not apply.

.PARAMETER Variant
    Build a measurement variant instead of the product (SLIA-034): the same
    staged source and patches, in `build/uc1/variants/<Variant>/`, and only one
    binary, the intermediate one unless -Release is given. `build/uc1/UC1/` is
    never touched. SLIAFlow never runs a variant; `measure-uc1.py` does.

.PARAMETER Defines
    With -Variant only: the preprocessor definitions that replace the
    product's `-DOPTIMIZE_KMEANS=1 -DPCA_PD=1`, for example
    `"-DOPTIMIZE_KMEANS=1 -DPCA_PD=0"`. A variant's warnings are printed but
    not held to the product's list, because other definitions compile other
    code.

.PARAMETER Release
    With -Variant only: build the release binary, without the per-stage CSV
    timings and intermediate images, instead of the intermediate one.
#>
[CmdletBinding()]
param(
    [switch]$Clean,

    [switch]$SkipBuild,

    [string]$PatchDirectory = (Join-Path $PSScriptRoot "uc1-patches"),

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9-]{0,31}$')]
    [string]$Variant,

    [string]$Defines,

    [switch]$Release
)

$ErrorActionPreference = "Stop"

# The definitions GUIDE section 3.1-B gives every optimised binary (OPT=1).
$productDefines = "-DOPTIMIZE_KMEANS=1 -DPCA_PD=1"

if (-not $Variant -and ($PSBoundParameters.ContainsKey("Defines") -or $Release)) {
    Write-Host "ERROR: -Defines and -Release apply only to a -Variant build." -ForegroundColor Red
    exit 1
}
if ($Variant -and -not $PSBoundParameters.ContainsKey("Defines")) {
    $Defines = $productDefines
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$vendoredRoot = Join-Path $repositoryRoot "workspace\components\UC1_Brain_Tumor-GPU_optimization\UC1_Brain_Tumor-GPU_optimization"
$vendoredSource = Join-Path $vendoredRoot "gpu_single_bsq\source"
$vendoredModel = Join-Path $vendoredRoot "svm_model"

if ($Variant) {
    $stagedRoot = Join-Path $repositoryRoot "build\uc1\variants\$Variant"
} else {
    $stagedRoot = Join-Path $repositoryRoot "build\uc1\UC1"
}
$stagedSource = Join-Path $stagedRoot "gpu_single_bsq\source"
$stagedModel = Join-Path $stagedRoot "svm_model"
$stagedRgbOutput = Join-Path $stagedSource "output\rgb"

# The reference the hash assertion compares against: a fresh copy of the
# vendored source with the same patches applied, rebuilt on every run. A
# variant keeps its own, so building one never rewrites the product's.
if ($Variant) {
    $expectedSource = Join-Path $stagedRoot "expected\gpu_single_bsq\source"
} else {
    $expectedSource = Join-Path $repositoryRoot "build\uc1\expected\gpu_single_bsq\source"
}


# The GPU this build targets. `sm_120` compiles and executes natively on the
# RTX 5050, so there is no PTX-JIT fallback; the second -gencode emits PTX only
# so the binary survives a future GPU change.
$computeCapability = "120"

# The binaries this script builds. `Flags` is appended to the GUIDE section
# 3.1-B release command line; for the intermediate build that is exactly the
# difference GUIDE 3.1-B shows between the two. `ExpectedWarnings` are the
# compiler diagnostics that command line is known to emit. Their absence means
# the toolchain changed, not that the code improved.
$binaries = @(
    [PSCustomObject]@{
        Name = "stratum.opt.exe"
        Flags = ""
        Defines = $productDefines
        EnforceWarnings = $true
        ExpectedWarnings = @(
            @{ Code = "#550-D"; Where = "functions_cuda.cu line 63, num_th_last_block set but never used" },
            @{ Code = "C4068"; Where = "matrixlib.cpp lines 205, 221, 293, unknown pragma unroll" }
        )
    },
    [PSCustomObject]@{
        Name = "stratum.opt.intermediate.exe"
        Flags = "-lineinfo -DPROFILE_MODE -DINTERMEDIATE_OUTPUT"
        Defines = $productDefines
        EnforceWarnings = $true
        ExpectedWarnings = @(
            @{ Code = "#550-D"; Where = "functions_cuda.cu line 63, num_th_last_block set but never used" },
            @{ Code = "C4068"; Where = "matrixlib.cpp lines 205, 221, 293, unknown pragma unroll" }
        )
    }
)

# A variant is one of those two binaries, under the same name so that
# measure-uc1.py runs it the same way, with other definitions. Its warnings are
# reported, not enforced.
if ($Variant) {
    $variantName = if ($Release) { "stratum.opt.exe" } else { "stratum.opt.intermediate.exe" }
    $binaries = @($binaries | Where-Object { $_.Name -eq $variantName } | ForEach-Object {
        [PSCustomObject]@{
            Name = $_.Name
            Flags = $_.Flags
            Defines = $Defines
            EnforceWarnings = $false
            ExpectedWarnings = $_.ExpectedWarnings
        }
    })
}

# Files the build produces inside the staged source tree. They have no
# `workspace/components/` original, so the hash assertion expects them. Each
# binary brings its import library and export file.
$buildProductPatterns = @("output\*", ".uc1-runner.lock")
foreach ($binary in $binaries) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($binary.Name)
    $buildProductPatterns += @($binary.Name, "$stem.exp", "$stem.lib")
}

function Stop-WithError {
    param([string]$Message)

    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Get-VcVarsPath {
    $vsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vsWhere -PathType Leaf)) {
        Stop-WithError "vswhere.exe was not found at $vsWhere. Install the Visual Studio C++ workload."
    }

    $installationPath = & $vsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        Stop-WithError "vswhere found no Visual Studio installation carrying the MSVC x64 toolset."
    }

    $vcVarsPath = Join-Path $installationPath "VC\Auxiliary\Build\vcvars64.bat"
    if (-not (Test-Path -LiteralPath $vcVarsPath -PathType Leaf)) {
        Stop-WithError "vcvars64.bat was not found at $vcVarsPath."
    }
    return $vcVarsPath
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)

    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path
    $copiedCount = 0
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
        $relativePath = $file.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $target = Join-Path $Destination $relativePath
        $targetParent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetParent -PathType Container)) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copiedCount++
    }
    return $copiedCount
}

function Get-Patches {
    if (-not (Test-Path -LiteralPath $PatchDirectory -PathType Container)) {
        Stop-WithError "The patch folder is missing: $PatchDirectory"
    }
    # Name order is application order: the patches are numbered 0001, 0002...
    return @(Get-ChildItem -LiteralPath $PatchDirectory -Filter "*.patch" -File | Sort-Object Name)
}

function Invoke-Patches {
    param([string]$Directory, [object[]]$Patches)

    # Inside a repository, `git apply` reads patch paths from the repository
    # root and silently skips any file it then finds outside the current
    # folder, exiting 0. So it runs from the root, the staged folder is given
    # as a prefix, and a "Skipped patch" line is a failure like any other.
    $fullDirectory = [System.IO.Path]::GetFullPath($Directory)
    if (-not $fullDirectory.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-WithError "$Directory is outside the repository $repositoryRoot."
    }
    $relativeDirectory = $fullDirectory.Substring($repositoryRoot.Length).TrimStart('\').Replace('\', '/')

    foreach ($patch in $Patches) {
        # core.autocrlf is off for this call: the vendored sources are LF, and
        # the patched files must stay byte-for-byte what the patch describes.
        $output = & git -c core.autocrlf=false -C $repositoryRoot apply --verbose --whitespace=nowarn `
            "--directory=$relativeDirectory" $patch.FullName 2>&1 | ForEach-Object { $_.ToString() }
        $exitCode = $LASTEXITCODE
        $skipped = @($output | Where-Object { $_ -like "Skipped patch*" })
        $applied = @($output | Where-Object { $_ -like "Applied patch*" })
        if ($exitCode -ne 0 -or $skipped.Count -gt 0 -or $applied.Count -eq 0) {
            $output | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
            Stop-WithError "$($patch.Name) does not apply to $Directory. The vendored UC1 source has changed or the patch is wrong; the build does not continue without it."
        }
    }
}

function Test-IsBuildProduct {
    param([string]$RelativePath)

    foreach ($pattern in $buildProductPatterns) {
        if ($RelativePath -like $pattern) { return $true }
    }
    return $false
}

function Assert-StagedTreeIsUnchanged {
    param([string]$Original, [string]$Staged, [string]$Label)

    $originalRoot = (Resolve-Path -LiteralPath $Original).Path
    $stagedRootPath = (Resolve-Path -LiteralPath $Staged).Path

    $mismatches = @()
    $comparedCount = 0

    foreach ($file in Get-ChildItem -LiteralPath $originalRoot -Recurse -File) {
        $relativePath = $file.FullName.Substring($originalRoot.Length).TrimStart('\')
        $stagedFile = Join-Path $stagedRootPath $relativePath
        if (-not (Test-Path -LiteralPath $stagedFile -PathType Leaf)) {
            $mismatches += "MISSING  $Label\$relativePath"
            continue
        }
        $originalHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        $stagedHash = (Get-FileHash -LiteralPath $stagedFile -Algorithm SHA256).Hash
        if ($originalHash -ne $stagedHash) {
            $mismatches += "CHANGED  $Label\$relativePath`n           original $originalHash`n           staged   $stagedHash"
        }
        $comparedCount++
    }

    # A file that exists only in the staging area is either a build product or
    # an edit made by addition, which a per-file hash comparison alone would
    # never see.
    foreach ($file in Get-ChildItem -LiteralPath $stagedRootPath -Recurse -File) {
        $relativePath = $file.FullName.Substring($stagedRootPath.Length).TrimStart('\')
        if (Test-IsBuildProduct -RelativePath $relativePath) { continue }
        $originalFile = Join-Path $originalRoot $relativePath
        if (-not (Test-Path -LiteralPath $originalFile -PathType Leaf)) {
            $mismatches += "EXTRA    $Label\$relativePath"
        }
    }

    return [PSCustomObject]@{
        Label = $Label
        ComparedCount = $comparedCount
        Mismatches = $mismatches
    }
}

Write-Host "== STRATUM UC1 build =="
Write-Host "Vendored source: $vendoredSource"
Write-Host "Staged build:    $stagedRoot"
if ($Variant) {
    Write-Host "Variant:         $Variant, $($binaries[0].Name), $Defines"
}
Write-Host ""

if (-not (Test-Path -LiteralPath $vendoredSource -PathType Container)) {
    Stop-WithError "The vendored UC1 source is missing: $vendoredSource"
}
if (-not (Test-Path -LiteralPath $vendoredModel -PathType Container)) {
    Stop-WithError "The vendored SVM model is missing: $vendoredModel"
}

# Capture the toolchain before anything else, so a machine change is detected
# rather than assumed away. The binary is only ever proven against the versions
# recorded in the task card and docs/development/uc1_local_build.md.
Write-Host "-- Toolchain --"
# Piped through Write-Host so the versions appear where they belong in the
# transcript. A bare native call writes to the host's own stdout, which is
# flushed after this script's output rather than interleaved with it.
(& nvcc --version 2>&1) | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "nvcc is not on PATH. Install the CUDA Toolkit or open a CUDA-enabled shell."
}
(& nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv 2>&1) |
    ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "nvidia-smi failed. The GPU or its driver is unavailable."
}
Write-Host ""

if ($Clean -and (Test-Path -LiteralPath $stagedRoot -PathType Container)) {
    Write-Host "-- Cleaning $stagedRoot --"
    Remove-Item -LiteralPath $stagedRoot -Recurse -Force
}

Write-Host "-- Staging --"
$stagedSourceCount = Copy-Tree -Source $vendoredSource -Destination $stagedSource
$stagedModelCount = Copy-Tree -Source $vendoredModel -Destination $stagedModel
Write-Host "Copied $stagedSourceCount source file(s) and $stagedModelCount model file(s)."
Write-Host ""

# Every staged source file was just overwritten with its vendored original, so
# the patches always apply to the delivered code, never to an earlier result.
Write-Host "-- Patches ($PatchDirectory) --"
$patches = Get-Patches
Invoke-Patches -Directory $stagedSource -Patches $patches
foreach ($patch in $patches) {
    $patchHash = (Get-FileHash -LiteralPath $patch.FullName -Algorithm SHA256).Hash
    Write-Host "  applied  $($patch.Name)  $patchHash"
}
Write-Host "Applied $($patches.Count) patch(es) to the staged source."

# The binary creates neither output directory and fails quietly without them.
New-Item -ItemType Directory -Path $stagedRgbOutput -Force | Out-Null
Write-Host "Pre-created $stagedRgbOutput"
Write-Host ""

function Invoke-Uc1Build {
    param([string]$VcVarsPath, [PSCustomObject]$Binary)

    $stagedExecutable = Join-Path $stagedSource $Binary.Name
    Write-Host "-- Building $($Binary.Name) --"

    # The GUIDE section 3.1-B command line, transcribed. The only changes are
    # the architecture and the additional PTX-emitting -gencode.
    # `-allow-unsupported-compiler` is deliberately absent: nvcc 12.9 accepts
    # this MSVC, and adding it would suppress a real diagnostic on a future
    # toolchain.
    $outputFlags = "-lcublas -O3"
    if ($Binary.Flags) { $outputFlags += " $($Binary.Flags)" }
    $commandLines = @(
        "@echo off",
        "call `"$VcVarsPath`" >nul",
        "if errorlevel 1 exit /b 1",
        "cd /d `"$stagedSource`"",
        "if errorlevel 1 exit /b 1",
        "nvcc main.cu functions.cu functions_kmeans.cu functions_cuda.cu ^",
        "     HySimeFilter\hysime.cu HySimeFilter\hysimefunc.cu HySimeFilter\lib.cu ^",
        "     HySimeFilter\matrixlib.cpp HySimeFilter\matrixop.cpp ^",
        "     HySimeFilter\ompfunc.cpp HySimeFilter\svd.cpp ^",
        "     BitmapWriter.cpp data_loader.cpp ^",
        "     -IHySimeFilter\ -I. ^",
        "     -gencode arch=compute_$computeCapability,code=sm_$computeCapability ^",
        "     -gencode arch=compute_$computeCapability,code=compute_$computeCapability ^",
        "     -std=c++17 ^",
        "     $($Binary.Defines) ^",
        "     $outputFlags -o $($Binary.Name)",
        "exit /b %errorlevel%"
    )

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($Binary.Name)
    $batchPath = Join-Path $stagedRoot "build-$stem-generated.cmd"
    Set-Content -LiteralPath $batchPath -Value $commandLines -Encoding ASCII

    $buildOutput = & cmd.exe /c "`"$batchPath`"" 2>&1 | ForEach-Object { $_.ToString() }
    $buildExitCode = $LASTEXITCODE
    $buildOutput | ForEach-Object { Write-Host $_ }
    Write-Host ""

    if ($buildExitCode -ne 0) {
        Stop-WithError "nvcc exited with code $buildExitCode building $($Binary.Name). The staged sources were not modified; fix the toolchain, not the vendored source."
    }
    if (-not (Test-Path -LiteralPath $stagedExecutable -PathType Leaf)) {
        Stop-WithError "nvcc reported success but $stagedExecutable was not produced."
    }

    $executableSize = (Get-Item -LiteralPath $stagedExecutable).Length

    # The requirement is "only this binary's expected warnings may appear", so
    # both halves are enforced and both fail the build. A missing expected
    # warning means the toolchain or the source changed; an unexpected one means
    # this binary is not the one the evidence on the task card describes.
    # Reporting either in yellow and exiting 0 would leave the contract
    # unchecked, which is the same as not having it.
    Write-Host "-- Warnings: $($Binary.Name) --"
    $joinedOutput = $buildOutput -join "`n"
    $warningFailures = @()

    foreach ($warning in $Binary.ExpectedWarnings) {
        if ($joinedOutput -like "*$($warning.Code)*") {
            Write-Host "  present  $($warning.Code)  ($($warning.Where))"
        } else {
            Write-Host "  ABSENT   $($warning.Code)  ($($warning.Where))" -ForegroundColor Red
            $warningFailures += "expected warning $($warning.Code) did not appear ($($warning.Where))"
        }
    }

    # Every diagnostic line nvcc or cl emits, matched on the two forms they use:
    # `warning #550-D:` from nvcc and `warning C4068:` from MSVC. Anything that
    # is not one of the expected codes is unexpected by construction, so a new
    # diagnostic cannot slip through by being unlisted.
    $expectedCodes = $Binary.ExpectedWarnings | ForEach-Object { $_.Code }
    $unexpected = @{}
    foreach ($line in $buildOutput) {
        if ($line -notmatch 'warning\s+(#[0-9]+-[A-Z]|C[0-9]+)') { continue }
        $code = $Matches[1]
        if ($expectedCodes -contains $code) { continue }
        if (-not $unexpected.ContainsKey($code)) { $unexpected[$code] = $line.Trim() }
    }

    foreach ($code in ($unexpected.Keys | Sort-Object)) {
        Write-Host "  UNEXPECTED  $code" -ForegroundColor Red
        Write-Host "              $($unexpected[$code])" -ForegroundColor Red
        $warningFailures += "unexpected warning $code"
    }

    if (-not $Binary.EnforceWarnings) {
        # A variant compiles other code, so the product's list does not bind
        # it. What it emitted is listed above for the measurement record.
        if ($warningFailures.Count -gt 0) {
            Write-Host "  Variant build: the differences above are reported, not enforced."
        }
    } elseif ($warningFailures.Count -gt 0) {
        Write-Host ""
        Write-Host "  The vendored source is not to be silenced or 'fixed' to clear this." -ForegroundColor Red
        Write-Host "  Investigate the toolchain, then re-record the expected set on the task" -ForegroundColor Red
        Write-Host "  card if it has genuinely changed." -ForegroundColor Red
        Stop-WithError ("The build warning contract for $($Binary.Name) failed: " + ($warningFailures -join "; ") + ".")
    }
    Write-Host ""
    Write-Host "Produced $stagedExecutable ($executableSize bytes)."
    Write-Host ""
}

if ($SkipBuild) {
    Write-Host "-- Build skipped (-SkipBuild) --"
    Write-Host ""
} else {
    $vcVarsPath = Get-VcVarsPath
    Write-Host "vcvars64: $vcVarsPath"
    Write-Host ""
    foreach ($binary in $binaries) {
        Invoke-Uc1Build -VcVarsPath $vcVarsPath -Binary $binary
    }
}

# The compliance property - "the staged source is the vendored UC1 plus the
# versioned patches, and nothing else" - is re-tested on every build rather
# than trusted once. `build/` is gitignored, so `git status` proves nothing
# about the staged copy. The reference is rebuilt from scratch: a fresh copy of
# the vendored source with the same patches applied.
Write-Host "-- SHA-256 source assertion --"
if (Test-Path -LiteralPath $expectedSource -PathType Container) {
    Remove-Item -LiteralPath $expectedSource -Recurse -Force
}
Copy-Tree -Source $vendoredSource -Destination $expectedSource | Out-Null
Invoke-Patches -Directory $expectedSource -Patches $patches
Write-Host "  Reference: vendored source plus $($patches.Count) patch(es), in $expectedSource"

$results = @(
    (Assert-StagedTreeIsUnchanged -Original $expectedSource -Staged $stagedSource -Label "gpu_single_bsq\source"),
    (Assert-StagedTreeIsUnchanged -Original $vendoredModel -Staged $stagedModel -Label "svm_model")
)

$allMismatches = @()
foreach ($result in $results) {
    Write-Host "  $($result.Label): compared $($result.ComparedCount) file(s)."
    $allMismatches += $result.Mismatches
}

$vendoredMainHash = (Get-FileHash -LiteralPath (Join-Path $vendoredSource "main.cu") -Algorithm SHA256).Hash
$mainHash = (Get-FileHash -LiteralPath (Join-Path $stagedSource "main.cu") -Algorithm SHA256).Hash
Write-Host "  main.cu SHA-256, vendored: $vendoredMainHash"
Write-Host "  main.cu SHA-256, staged:   $mainHash"

if ($allMismatches.Count -gt 0) {
    Write-Host ""
    foreach ($mismatch in $allMismatches) { Write-Host "  $mismatch" -ForegroundColor Red }
    Stop-WithError "The staged tree is not the vendored UC1 plus the patches in $PatchDirectory. Change UC1 only through a patch there; re-stage with -Clean, and escalate if the difference is intentional."
}

Write-Host "  All staged files equal workspace\components plus the patches." -ForegroundColor Green
Write-Host ""
if ($Variant) {
    Write-Host "Variant $Variant ($($binaries[0].Name), $Defines) is in $stagedSource."
    Write-Host "SLIAFlow does not run it; measure it with scripts\development\measure-uc1.py."
} else {
    Write-Host "Press Capture in SLIAFlow to run stratum.opt.intermediate.exe on the configured cube."
}
exit 0
