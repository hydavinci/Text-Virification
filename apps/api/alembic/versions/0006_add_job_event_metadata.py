"""add job event metadata

Revision ID: 0006_add_job_event_metadata
Revises: 0005_normalize_job_scenarios
Create Date: 2026-08-17 08:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_add_job_event_metadata"
down_revision = "0005_normalize_job_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_events",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_events", "metadata_json")
