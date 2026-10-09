"""inbox runs/files (журнал массовой загрузки файлов)

Revision ID: f2a7c1b93d45
Revises: c4d81f0a7b52
Create Date: 2026-10-09 10:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a7c1b93d45'
down_revision: str | None = 'c4d81f0a7b52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Папка-приёмник: файлы кладут в data/inbox (в контейнере это bind-mount
    # на хост), backend индексирует их по кнопке и переносит в постоянную
    # библиотеку. Отчёт о прогоне живёт в БД, а не в логе: разрыв процесса
    # посреди прогона должен быть виден и возобновляем.
    op.create_table('inbox_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('trigger', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('inbox_dir', sa.String(length=1024), nullable=False),
        sa.Column('scanned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('indexed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('replaced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_inbox_runs_status', 'inbox_runs', ['status'])
    op.create_index('ix_inbox_runs_started_at', 'inbox_runs', ['started_at'])

    op.create_table('inbox_files',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('rel_path', sa.String(length=1024), nullable=False),
        sa.Column('abs_path', sa.String(length=1024), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False, server_default='discovered'),
        sa.Column('reason_code', sa.String(length=64), nullable=True),
        sa.Column('reason_text', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('document_id', sa.String(length=36), nullable=True),
        sa.Column('final_path', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['run_id'], ['inbox_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'rel_path', name='uq_inbox_files_run_rel_path'),
    )
    op.create_index('ix_inbox_files_run_id', 'inbox_files', ['run_id'])
    op.create_index('ix_inbox_files_sha256', 'inbox_files', ['sha256'])
    op.create_index('ix_inbox_files_reason_code', 'inbox_files', ['reason_code'])
    op.create_index('ix_inbox_files_run_status', 'inbox_files', ['run_id', 'status'])


def downgrade() -> None:
    op.drop_table('inbox_files')
    op.drop_index('ix_inbox_runs_started_at', table_name='inbox_runs')
    op.drop_index('ix_inbox_runs_status', table_name='inbox_runs')
    op.drop_table('inbox_runs')