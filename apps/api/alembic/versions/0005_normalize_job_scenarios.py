"""normalize job scenarios

Revision ID: 0005_normalize_job_scenarios
Revises: 0004_add_job_check_options
Create Date: 2026-08-17 08:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_normalize_job_scenarios"
down_revision = "0004_add_job_check_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE jobs
            SET scenario = CASE scenario
                WHEN 'education' THEN 'academic'
                WHEN 'medical' THEN 'technical'
                ELSE scenario
            END
            WHERE scenario IN ('education', 'medical')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE jobs
            SET scenario = CASE scenario
                WHEN 'academic' THEN 'education'
                WHEN 'technical' THEN 'medical'
                ELSE scenario
            END
            WHERE scenario IN ('academic', 'technical')
            """
        )
    )
