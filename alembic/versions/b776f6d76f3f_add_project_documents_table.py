"""add_project_documents_table

Revision ID: b776f6d76f3f
Revises: 8e828a4be6f5
Create Date: 2026-09-17 16:42:49.072404

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b776f6d76f3f'
down_revision: Union[str, Sequence[str], None] = '8e828a4be6f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if 'project_documents' not in tables:
        op.create_table(
            'project_documents',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('company_id', sa.UUID(), nullable=False),
            sa.Column('project_id', sa.UUID(), nullable=False),
            sa.Column('file_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('file_size', sa.Numeric(precision=12, scale=0), nullable=False, server_default='0'),
            sa.Column('file_type', sa.String(length=100), nullable=False, server_default='application/octet-stream'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('uploaded_by', sa.UUID(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['file_id'], ['file_objects.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_project_documents_company_id'), 'project_documents', ['company_id'], unique=False)
        op.create_index(op.f('ix_project_documents_project_id'), 'project_documents', ['project_id'], unique=False)
        op.create_index('idx_project_documents_project', 'project_documents', ['project_id'], unique=False)
        op.create_index('idx_project_documents_company', 'project_documents', ['company_id'], unique=False)

    from app.db.rls import enable_rls
    enable_rls("project_documents")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_project_documents_company', table_name='project_documents')
    op.drop_index('idx_project_documents_project', table_name='project_documents')
    op.drop_index(op.f('ix_project_documents_project_id'), table_name='project_documents')
    op.drop_index(op.f('ix_project_documents_company_id'), table_name='project_documents')
    op.drop_table('project_documents')
