"""project versions

Revision ID: a1c74e5b93d2
Revises: 605775f630d8
Create Date: 2026-10-02 12:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.models


revision: str = 'a1c74e5b93d2'
down_revision: str | None = '605775f630d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('project_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('section_name', sa.String(length=255), nullable=True),
        sa.Column('kind', sa.Enum('section', 'literature_review', 'discussion',
                                  'data_comparison', 'gap_analysis',
                                  'draft_analysis', 'report',
                                  name='generationkind', native_enum=False),
                  nullable=False),
        sa.Column('content_md', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('citation_map', sa.JSON(), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', app.db.models.UTCDateTime(timezone=True),
                  nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
                                name=op.f('fk_project_versions_created_by_users'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                name=op.f('fk_project_versions_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['research_sessions.id'],
                                name=op.f('fk_project_versions_session_id_research_sessions'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('project_versions', schema=None) as batch_op:
        batch_op.create_index('ix_project_versions_created_at', ['created_at'],
                              unique=False)
        batch_op.create_index('ix_project_versions_project_created',
                              ['project_id', 'created_at'], unique=False)
        batch_op.create_index('ix_project_versions_project_id', ['project_id'],
                              unique=False)
        batch_op.create_index('ix_project_versions_session_id', ['session_id'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('project_versions', schema=None) as batch_op:
        batch_op.drop_index('ix_project_versions_session_id')
        batch_op.drop_index('ix_project_versions_project_id')
        batch_op.drop_index('ix_project_versions_project_created')
        batch_op.drop_index('ix_project_versions_created_at')
    op.drop_table('project_versions')