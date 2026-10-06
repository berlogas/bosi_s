"""message checks (цитаты и обоснованность ответа)

Revision ID: c4d81f0a7b52
Revises: a1c74e5b93d2
Create Date: 2026-10-06 12:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4d81f0a7b52'
down_revision: str | None = 'a1c74e5b93d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Отчёты citation_guard/grounding для ответа ассистента: без колонки
    # предупреждения показывались бы только при первом показе ответа и
    # терялись после перезагрузки страницы (история читается из БД).
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('checks', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('checks')
