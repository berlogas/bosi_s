"""Add order column to projects table

Revision ID: add_order_to_project
Revises: 8f557676cc89
Create Date: 2026-11-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_order_to_project'
down_revision = '8f557676cc89'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('order', sa.Integer(), nullable=False,
                                         server_default='0'))


def downgrade() -> None:
    op.drop_column('projects', 'order')
