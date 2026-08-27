# SLIAFlow Cleanup and Next Steps

Checked on 2026-08-27. Nothing listed below has been deleted.

## Safe deletion candidates

After checking the exact paths, these two quarantined copies can be deleted:

1. `C:\stratum\workspace\legacy\SLIAFlow-nested-duplicate`
   - Size: about 12.38 GiB.
   - This is the old duplicate repository. The working project is
     `C:\stratum`.
2. `C:\stratum\workspace\legacy\SLIAFlow-extension-prototype`
   - Size: about 0.13 MiB.
   - This contains ignored runtime artifacts left by the discarded test
     prototype. The tracked prototype source remains recoverable from Git
     history.

Close Slicer first. In File Explorer, open
`C:\stratum\workspace\legacy`, check each full folder name, and delete only
those two folders. Do not delete the `legacy` parent folder. Prefer the Recycle
Bin; if Windows says the large folder must be permanently deleted, continue only
after confirming the exact path again.

## Do not delete

- `C:\stratum\apps\SR\Slicer-build` - the expensive Slicer build.
- `C:\stratum\build\SLIAFlow` - keep the current launcher for now. This small
  extension build will be regenerated in task SLIA-003.
- `C:\stratum\source`, `C:\stratum\.git`, or the other project folders.
- `C:\Users\AlejandroHerrera\Desktop\stratum` or the source files in
  Downloads. Keep them until task SLIA-002 copies and verifies the required
  material.

The two files that should still exist after cleanup are:

- `C:\stratum\apps\SR\Slicer-build\Slicer.exe`
- `C:\stratum\build\SLIAFlow\SlicerWithSLIAFlow.exe`

## What to do next

1. Finish SLIA-001: review this foundation, run an independent AI review, give
   final approval, then separately approve its commit and merge.
2. Start SLIA-002: copy and verify the useful project documents and reference
   projects. Do not delete the originals yet.
3. Start SLIA-003: create a clean SLIAFlow scripted-module scaffold and rebuild
   only `C:\stratum\build\SLIAFlow`. Do not rebuild Slicer.
4. Start SLIA-004: create the two black side-by-side views and the genuine-result
   waiting message.
5. Start SLIA-005: connect the laptop camera to the left view. This completes the
   first camera-only demo; the right view stays black until genuine UC1 data is
   connected later.

Work on one task at a time. The immediate instruction to give Codex is:

> Move SLIA-001 to review and run an independent AI review.
