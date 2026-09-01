# Task 0 Report: Close unified-pipeline prerequisites

**Date:** 2026-09-01
**Base:** `f60a5a88dee2adb8a76d8157a10f443ed2ceb40a`
**Status:** Implemented; PostgreSQL-gated tests were added but could not run locally.

## Summary

Closed the three load-bearing findings without adding OCR dependencies, parsers,
or exporters:

1. Broker-confirmed rescue publications now persist suppression in
   `jobs.rescue_last_published_at`. Periodic recovery claims exclude suppressed
   generations. Worker lease acquisition/progress and explicit publication
   failure clear suppression with database compare-and-set guards.
2. Unreleased migration `0004_finalize_verification_pipeline` now remaps
   existing issue block identity to the synthesized `file-0` block and adds a
   document/block foreign key. Canonical result validation checks block
   existence, ownership through the result, containment, exact local/global
   offset mapping, and block-slice text.
3. Artifact keys now use a centralized `artifacts/<job_id>/...` builder and
   validator. Persistence rejects non-owned keys, and cleanup validates
   ownership before deleting files or result metadata.

## Rescue publication crash windows

- **Reservation committed, process crashes before broker publication:** the
  unconfirmed generation remains due after the short publication reservation
  interval.
- **Broker accepts publication, process crashes before confirmation marker:**
  the same generation can be republished once the reservation expires. A later
  successful marker suppresses subsequent Beat publications.
- **Worker claims before a stale marker write:** lease acquisition clears the
  marker and changes recovery state; the stale marker loses its compare-and-set
  because the job has a live lease.
- **Broker publication fails:** the matching generation is explicitly reset
  and scheduled for the later failure-retry tick.
- **Confirmed publication during worker outage:** Beat does not publish the
  durable broker message indefinitely; the broker retains responsibility for
  delivery until a worker claim resets recovery state.

## Migration decision

Amended `0004_finalize_verification_pipeline` because it is the current
unreleased migration introduced at the supplied base and its own synthesized
block data required correction. Upgrade from `0003_add_job_leases` now:

- creates `file-0` for every persisted document;
- rewrites any issue carrying block-local identity to `file-0`, with
  `block_start = start` and `block_end = end`;
- creates `fk_verification_issues_document_block`.

Downgrade explicitly drops that foreign key before dropping
`document_blocks`. A real PostgreSQL upgrade/data/downgrade test is gated by
`TEST_DATABASE_URL`.

## Artifact ownership

The centralized storage-key implementation rejects empty keys, NULs,
backslashes, POSIX and drive-qualified absolute paths, empty/dot/traversal
segments, compatibility upload paths, infrastructure paths, and another job's
artifact namespace. Filesystem resolution still rejects symlink/reparse
crossings and root escapes.

Cleanup uses `delete_artifact(job_id, storage_key)`. Invalid existing rows fail
closed before the job directory or result aggregate is deleted, retaining the
artifact metadata for operator remediation. Partial deletion failures retain
metadata and retry missing/remaining files safely on the next cleanup run.

## TDD evidence

- Rescue tests first failed because confirmed publications were emitted again
  after the reservation interval.
- Canonical validation tests first failed because missing block IDs and
  incorrect local offsets were accepted; ORM parity also lacked the block
  foreign key.
- Artifact tests first failed because no job-owned builder/deletion API
  existed and cleanup deleted another job's referenced artifact.

## Verification

- Focused backend: `138 passed, 41 skipped`.
- Full backend: `346 passed, 55 skipped`.
- Ruff: passed for `src` and `tests`.
- mypy: passed for `src` (`58` source files).
- Alembic offline upgrade to head: passed.
- Alembic offline downgrade `head:base`: passed.
- `git diff --check`: passed.
- Frontend tests/build: not run; no frontend contract changed.

## Skips and limitations

- `TEST_DATABASE_URL` was not set, so real PostgreSQL migration, locking,
  compare-and-set, and persistence tests were skipped. SQLite was not used as a
  substitute.
- Docker was not used because the daemon is unavailable.
- Live API end-to-end tests remained skipped because `LIVE_API_URL` was not
  set.

## Concerns

- The broker-confirmed suppression model intentionally relies on the configured
  durable broker after a successful publish. The database avoids both periodic
  infinite republishing and stale-marker stranding, while the bounded
  publish-before-marker window can still produce a duplicate delivery; worker
  lease/CAS semantics make that duplicate a safe no-op.
