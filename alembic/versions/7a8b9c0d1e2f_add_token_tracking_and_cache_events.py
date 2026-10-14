"""add token tracking and cache events

Revision ID: 7a8b9c0d1e2f
Revises: 2bd956ecdba6
Create Date: 2026-10-13 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = '2bd956ecdba6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update ai_usage_records with additional metadata fields
    with op.batch_alter_table('ai_usage_records') as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('analysis_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('candidate_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('generation_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('usage_source', sa.String(length=50), nullable=False, server_default='provider_reported'))
        batch_op.add_column(sa.Column('cached_input_tokens', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('estimated_input_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('estimated_output_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('estimated_total_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('request_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=50), nullable=False, server_default='success'))
        batch_op.add_column(sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('metadata_json', sa.JSON(), nullable=True))
        batch_op.create_index('ix_ai_usage_project', ['project_id'])
        batch_op.create_index('ix_ai_usage_analysis', ['analysis_id'])
        batch_op.create_index('ix_ai_usage_operation', ['operation'])
        batch_op.create_index('ix_ai_usage_request_id', ['request_id'])

    # 2. Create cache_event_records table
    op.create_table(
        'cache_event_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('analysis_id', sa.String(length=36), nullable=True),
        sa.Column('experiment_id', sa.String(length=36), nullable=True),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('cache_type', sa.String(length=50), nullable=False),
        sa.Column('cache_hit', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_requests_avoided', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('estimated_tokens_avoided', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('savings_baseline', sa.String(length=255), nullable=True),
        sa.Column('reused_record_id', sa.String(length=36), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 3. Create analysis_cache_records table
    op.create_table(
        'analysis_cache_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='python'),
        sa.Column('objective', sa.String(length=50), nullable=False, server_default='balanced'),
        sa.Column('symbol_name', sa.String(length=255), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table('analysis_cache_records')
    op.drop_table('cache_event_records')
    with op.batch_alter_table('ai_usage_records') as batch_op:
        batch_op.drop_index('ix_ai_usage_request_id')
        batch_op.drop_index('ix_ai_usage_operation')
        batch_op.drop_index('ix_ai_usage_analysis')
        batch_op.drop_index('ix_ai_usage_project')
        batch_op.drop_column('metadata_json')
        batch_op.drop_column('latency_ms')
        batch_op.drop_column('status')
        batch_op.drop_column('request_id')
        batch_op.drop_column('estimated_total_tokens')
        batch_op.drop_column('estimated_output_tokens')
        batch_op.drop_column('estimated_input_tokens')
        batch_op.drop_column('cached_input_tokens')
        batch_op.drop_column('usage_source')
        batch_op.drop_column('attempt_number')
        batch_op.drop_column('generation_number')
        batch_op.drop_column('candidate_id')
        batch_op.drop_column('analysis_id')
        batch_op.drop_column('project_id')
