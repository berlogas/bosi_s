"""add schema_version to document_chunks

Revision ID: add_schema_version
Revises: f2a7c1b93d45
Create Date: 2026-10-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_schema_version'
down_revision = 'f2a7c1b93d45'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('document_chunks', sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'))

def downgrade() -> None:
    op.drop_column('document_chunks', 'schema_version')
