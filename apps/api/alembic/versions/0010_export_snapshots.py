"""persist export snapshots and index recoverable exports

Revision ID: 0010_export_snapshots
Revises: 0009_index_queued_exports
Create Date: 2026-08-17 19:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_export_snapshots"
down_revision = "0009_index_queued_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exports",
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE exports
            SET status = 'failed',
                error_code = 'export_snapshot_unavailable',
                error_message = '导出任务缺少不可变快照，请重新创建。',
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'processing')
              AND snapshot IS NULL
            """
        )
    )
    op.drop_index("ix_exports_queued_created_at", table_name="exports")
    op.create_index(
        "ix_exports_recoverable_updated_at",
        "exports",
        ["status", "updated_at", "export_id"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE exports
            SET warnings = COALESCE(
                (
                    SELECT jsonb_agg(
                        CASE
                            WHEN jsonb_typeof(item.value) = 'object' THEN
                                to_jsonb(
                                    COALESCE(
                                        item.value ->> 'code',
                                        'legacy_export_warning'
                                    )
                                    || ': '
                                    || COALESCE(item.value ->> 'message', '')
                                    || ' [issue_id='
                                    || COALESCE(
                                        item.value ->> 'issue_id',
                                        '00000000-0000-0000-0000-000000000000'
                                    )
                                    || '; block_id='
                                    || COALESCE(item.value ->> 'block_id', 'legacy')
                                    || ']'
                                )
                            ELSE item.value
                        END
                        ORDER BY item.ordinality
                    )
                    FROM jsonb_array_elements(exports.warnings)
                    WITH ORDINALITY AS item(value, ordinality)
                ),
                '[]'::jsonb
            )
            """
        )
    )
    op.drop_index("ix_exports_recoverable_updated_at", table_name="exports")
    op.create_index(
        "ix_exports_queued_created_at",
        "exports",
        ["created_at", "export_id"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_column("exports", "snapshot")
