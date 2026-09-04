"""add verified review revision provenance

Revision ID: 0012_add_revision_provenance
Revises: 0011_add_artifact_reservation_version
Create Date: 2026-09-03 00:00:00
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections import deque
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_add_revision_provenance"
down_revision = "0011_add_artifact_reservation_version"
branch_labels = None
depends_on = None

MAX_REVISION_TEXT_CODEPOINTS = 5_000_000
MAX_REVISION_TEXT_UTF8_BYTES = 25 * 1024 * 1024
MAX_VERIFICATION_ISSUES = 100_000
MAX_REVIEW_DERIVATION_STATES = 100_000
MAX_REVIEW_DERIVATION_WORK = 25_000_000
VERIFIED_PROVENANCE_STATE = "verified"
LEGACY_UNAVAILABLE_PROVENANCE_STATE = "legacy_unavailable"
DERIVATION_ISSUE_INDEX = "ix_verification_issues_run_start_end_issue_index"


def upgrade() -> None:
    op.add_column(
        "review_revisions",
        sa.Column(
            "verified_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "review_revisions",
        sa.Column(
            "provenance_state",
            sa.String(length=32),
            nullable=False,
            server_default=LEGACY_UNAVAILABLE_PROVENANCE_STATE,
        ),
    )
    op.create_check_constraint(
        "ck_review_revisions_provenance_state",
        "review_revisions",
        "("
        "provenance_state = 'verified' "
        "AND verified_provenance IS NOT NULL "
        "AND jsonb_typeof(verified_provenance) = 'object'"
        ") OR ("
        "provenance_state = 'legacy_unavailable' "
        "AND verified_provenance IS NULL"
        ")",
    )
    op.create_index(
        DERIVATION_ISSUE_INDEX,
        "verification_issues",
        ["verification_run_id", "start", "end", "issue_index"],
    )
    _backfill_original_result_provenance()
    op.drop_index(DERIVATION_ISSUE_INDEX, table_name="verification_issues")
    op.alter_column(
        "review_revisions",
        "provenance_state",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_revisions_provenance_state",
        "review_revisions",
        type_="check",
    )
    op.drop_column("review_revisions", "provenance_state")
    op.drop_column("review_revisions", "verified_provenance")


def _backfill_original_result_provenance() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _review_revision_derivation_seen (
            review_revision_id uuid NOT NULL,
            source_index integer NOT NULL,
            target_index integer NOT NULL,
            PRIMARY KEY (
                review_revision_id,
                source_index,
                target_index
            )
        ) ON COMMIT DROP
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION pg_temp._review_revision_derivable(
            p_revision_id uuid,
            p_source text,
            p_target text,
            p_run_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_length integer := char_length(p_source);
            target_length integer := char_length(p_target);
            source_queue integer[] := array_fill(
                0,
                ARRAY[{MAX_REVIEW_DERIVATION_STATES}]
            );
            target_queue integer[] := array_fill(
                0,
                ARRAY[{MAX_REVIEW_DERIVATION_STATES}]
            );
            queue_head integer := 1;
            queue_tail integer := 1;
            source_index integer;
            target_index integer;
            next_source_index integer;
            issue_record record;
            replacement text;
            unchanged text;
            work_used bigint := 0;
            issue_count bigint;
        BEGIN
            IF source_length > {MAX_REVISION_TEXT_CODEPOINTS}
                OR target_length > {MAX_REVISION_TEXT_CODEPOINTS}
                OR octet_length(p_source) > {MAX_REVISION_TEXT_UTF8_BYTES}
                OR octet_length(p_target) > {MAX_REVISION_TEXT_UTF8_BYTES}
            THEN
                RETURN FALSE;
            END IF;

            SELECT count(*)
            INTO issue_count
            FROM verification_issues
            WHERE verification_run_id = p_run_id;
            IF issue_count > {MAX_VERIFICATION_ISSUES}
                OR EXISTS (
                    SELECT 1
                    FROM verification_issues
                    WHERE verification_run_id = p_run_id
                      AND (
                        start < 0
                        OR "end" <= start
                        OR "end" > source_length
                        OR substring(
                            p_source
                            FROM start + 1
                            FOR "end" - start
                        ) <> original
                        OR jsonb_typeof(alternatives) <> 'array'
                      )
                )
            THEN
                RETURN FALSE;
            END IF;

            IF p_source = p_target THEN
                RETURN TRUE;
            END IF;

            DELETE FROM pg_temp._review_revision_derivation_seen
            WHERE review_revision_id = p_revision_id;
            INSERT INTO pg_temp._review_revision_derivation_seen
                (review_revision_id, source_index, target_index)
            VALUES (p_revision_id, 0, 0);
            source_queue[1] := 0;
            target_queue[1] := 0;

            WHILE queue_head <= queue_tail LOOP
                source_index := source_queue[queue_head];
                target_index := target_queue[queue_head];
                queue_head := queue_head + 1;

                IF source_index = source_length THEN
                    IF target_index = target_length THEN
                        RETURN TRUE;
                    END IF;
                    CONTINUE;
                END IF;
                IF source_index > source_length
                    OR target_index > target_length
                THEN
                    CONTINUE;
                END IF;

                FOR issue_record IN
                    SELECT "end", suggestion, alternatives
                    FROM verification_issues
                    WHERE verification_run_id = p_run_id
                      AND start = source_index
                    ORDER BY "end", issue_index
                LOOP
                    FOR replacement IN
                        SELECT candidate
                        FROM (
                            SELECT issue_record.suggestion AS candidate
                            UNION
                            SELECT value
                            FROM jsonb_array_elements_text(
                                issue_record.alternatives
                            ) AS alternative(value)
                        ) AS replacements
                        WHERE candidate IS NOT NULL
                    LOOP
                        work_used := work_used
                            + char_length(replacement)
                            + 1;
                        IF work_used > {MAX_REVIEW_DERIVATION_WORK} THEN
                            RETURN FALSE;
                        END IF;
                        IF target_index + char_length(replacement)
                            <= target_length
                            AND substring(
                                p_target
                                FROM target_index + 1
                                FOR char_length(replacement)
                            ) = replacement
                        THEN
                            INSERT INTO pg_temp._review_revision_derivation_seen
                                (
                                    review_revision_id,
                                    source_index,
                                    target_index
                                )
                            VALUES (
                                p_revision_id,
                                issue_record."end",
                                target_index + char_length(replacement)
                            )
                            ON CONFLICT DO NOTHING;
                            IF FOUND THEN
                                IF queue_tail
                                    >= {MAX_REVIEW_DERIVATION_STATES}
                                THEN
                                    RETURN FALSE;
                                END IF;
                                queue_tail := queue_tail + 1;
                                source_queue[queue_tail] :=
                                    issue_record."end";
                                target_queue[queue_tail] :=
                                    target_index
                                    + char_length(replacement);
                            END IF;
                        END IF;
                    END LOOP;
                END LOOP;

                SELECT COALESCE(min(start), source_length)
                INTO next_source_index
                FROM verification_issues
                WHERE verification_run_id = p_run_id
                  AND start > source_index;
                unchanged := substring(
                    p_source
                    FROM source_index + 1
                    FOR next_source_index - source_index
                );
                work_used := work_used + char_length(unchanged) + 1;
                IF work_used > {MAX_REVIEW_DERIVATION_WORK} THEN
                    RETURN FALSE;
                END IF;
                IF target_index + char_length(unchanged) <= target_length
                    AND substring(
                        p_target
                        FROM target_index + 1
                        FOR char_length(unchanged)
                    ) = unchanged
                THEN
                    INSERT INTO pg_temp._review_revision_derivation_seen
                        (
                            review_revision_id,
                            source_index,
                            target_index
                        )
                    VALUES (
                        p_revision_id,
                        next_source_index,
                        target_index + char_length(unchanged)
                    )
                    ON CONFLICT DO NOTHING;
                    IF FOUND THEN
                        IF queue_tail >= {MAX_REVIEW_DERIVATION_STATES} THEN
                            RETURN FALSE;
                        END IF;
                        queue_tail := queue_tail + 1;
                        source_queue[queue_tail] := next_source_index;
                        target_queue[queue_tail] :=
                            target_index + char_length(unchanged);
                    END IF;
                END IF;
            END LOOP;
            RETURN FALSE;
        END;
        $$
        """
    )
    op.execute(
        """
        UPDATE review_revisions AS revision
        SET
            verified_provenance = jsonb_build_object(
                'kind', 'original_result',
                'job_id', run.job_id,
                'base_result', jsonb_build_object(
                    'document_id', revision.document_id,
                    'verification_run_id', revision.verification_run_id,
                    'source_version', revision.source_version,
                    'text_sha256', encode(
                        sha256(convert_to(document.text, 'UTF8')),
                        'hex'
                    )
                ),
                'revision_text_sha256', encode(
                    sha256(convert_to(revision.text, 'UTF8')),
                    'hex'
                )
            ),
            provenance_state = 'verified'
        FROM verification_runs AS run
        JOIN documents AS document
          ON document.document_id = run.document_id
         AND document.job_id = run.job_id
        WHERE revision.verification_run_id = run.verification_run_id
          AND revision.document_id = run.document_id
          AND revision.source_version = document.source_version
          AND revision.kind = 'review'
          AND pg_temp._review_revision_derivable(
              revision.review_revision_id,
              document.text,
              revision.text,
              revision.verification_run_id
          )
        """
    )
    op.execute("DROP FUNCTION pg_temp._review_revision_derivable(uuid, text, text, uuid)")
    op.execute("DROP TABLE pg_temp._review_revision_derivation_seen")


def _derive_original_result_provenance(
    *,
    job_id: str,
    document_id: str,
    verification_run_id: str,
    source_version: str,
    source_text: str,
    revision_kind: str,
    revision_text: str,
    issues: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    if revision_kind != "review":
        return None
    if not _text_within_limits(source_text) or not _text_within_limits(
        revision_text
    ):
        return None
    if len(issues) > MAX_VERIFICATION_ISSUES:
        return None
    if not _derives_from_original_result(source_text, revision_text, issues):
        return None
    return {
        "kind": "original_result",
        "job_id": job_id,
        "base_result": {
            "document_id": document_id,
            "verification_run_id": verification_run_id,
            "source_version": source_version,
            "text_sha256": _text_sha256(source_text),
        },
        "revision_text_sha256": _text_sha256(revision_text),
    }


def _derives_from_original_result(
    source: str,
    target: str,
    issues: Sequence[Mapping[str, object]],
) -> bool:
    if source == target:
        return True
    replacements_by_start: dict[int, list[tuple[int, str]]] = {}
    for issue in issues:
        start = issue.get("start")
        end = issue.get("end")
        suggestion = issue.get("suggestion")
        alternatives = issue.get("alternatives")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(source)
            or not isinstance(alternatives, list)
        ):
            return False
        original = issue.get("original", source[start:end])
        if not isinstance(original, str) or source[start:end] != original:
            return False
        candidates = [
            candidate
            for candidate in (suggestion, *alternatives)
            if isinstance(candidate, str)
        ]
        for replacement in dict.fromkeys(candidates):
            replacements_by_start.setdefault(start, []).append(
                (end, replacement)
            )
    if not replacements_by_start:
        return False

    starts = sorted(replacements_by_start)
    pending = deque([(0, 0)])
    visited: set[tuple[int, int]] = set()
    work = 0
    while pending:
        source_index, target_index = pending.popleft()
        state = (source_index, target_index)
        if state in visited:
            continue
        visited.add(state)
        if len(visited) > MAX_REVIEW_DERIVATION_STATES:
            return False
        if source_index == len(source):
            if target_index == len(target):
                return True
            continue
        if source_index > len(source) or target_index > len(target):
            continue

        for source_end, replacement in replacements_by_start.get(
            source_index,
            (),
        ):
            work += len(replacement) + 1
            if work > MAX_REVIEW_DERIVATION_WORK:
                return False
            if target.startswith(replacement, target_index):
                pending.append(
                    (source_end, target_index + len(replacement))
                )

        next_start_index = bisect_right(starts, source_index)
        next_source_index = (
            starts[next_start_index]
            if next_start_index < len(starts)
            else len(source)
        )
        unchanged = source[source_index:next_source_index]
        work += len(unchanged) + 1
        if work > MAX_REVIEW_DERIVATION_WORK:
            return False
        if target.startswith(unchanged, target_index):
            pending.append(
                (next_source_index, target_index + len(unchanged))
            )
    return False


def _text_within_limits(value: str) -> bool:
    return (
        len(value) <= MAX_REVISION_TEXT_CODEPOINTS
        and len(value.encode("utf-8")) <= MAX_REVISION_TEXT_UTF8_BYTES
    )


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
