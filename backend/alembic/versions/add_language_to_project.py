"""Add language field to projects table

Revision ID: add_language_to_project
Revises: add_doc_version
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_language_to_project'
down_revision = 'add_doc_version'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('projects', sa.Column('language', sa.String(length=10), nullable=False, server_default='ru'))

def downgrade() -> None:
    op.drop_column('projects', 'language')
