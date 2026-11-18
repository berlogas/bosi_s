"""add doc_version to documents

Revision ID: add_doc_version
Revises: add_schema_version
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_doc_version'
down_revision = '61b31f768a1c'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('documents', sa.Column('doc_version', sa.Integer(), nullable=False, server_default='1'))

def downgrade() -> None:
    op.drop_column('documents', 'doc_version')
