"""create_user_accounts_and_evolution_schema

Revision ID: 2bd956ecdba6
Revises: 
Create Date: 2026-10-10 21:33:11.637133

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2bd956ecdba6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('username', sa.String(length=50), nullable=False, unique=True),
        sa.Column('email', sa.String(length=255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 2. refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 3. projects table
    op.create_table(
        'projects',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='python'),
        sa.Column('entry_point', sa.String(length=500), nullable=True),
        sa.Column('test_command', sa.String(length=1000), nullable=True),
        sa.Column('optimization_objective', sa.String(length=50), nullable=False, server_default='balanced'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 4. project_files table
    op.create_table(
        'project_files',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='python'),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 5. code_versions table
    op.create_table(
        'code_versions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_original', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='python'),
        sa.Column('line_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 6. experiments table
    op.create_table(
        'experiments',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_file', sa.String(length=500), nullable=False),
        sa.Column('source_hash', sa.String(length=64), nullable=False),
        sa.Column('source_content', sa.Text(), nullable=False),
        sa.Column('language', sa.String(length=50), nullable=False),
        sa.Column('objective', sa.String(length=50), nullable=False, server_default='balanced'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='queued'),
        sa.Column('generations_total', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('generations_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('population_size', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('benchmark_repetitions', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('execution_timeout', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('memory_limit_mb', sa.Integer(), nullable=False, server_default='256'),
        sa.Column('fitness_weights', sa.JSON(), nullable=True),
        sa.Column('best_candidate_id', sa.String(length=36), nullable=True),
        sa.Column('best_improvement_percent', sa.Float(), nullable=True),
        sa.Column('total_candidates', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_candidates', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('config_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 7. experiment_generations table
    op.create_table(
        'experiment_generations',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('experiment_id', sa.String(length=36), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('generation_number', sa.Integer(), nullable=False),
        sa.Column('candidates_generated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('candidates_valid', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('candidates_tested', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('best_fitness', sa.Float(), nullable=True),
        sa.Column('best_candidate_id', sa.String(length=36), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('memory_context_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 8. mutation_candidates table
    op.create_table(
        'mutation_candidates',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('experiment_id', sa.String(length=36), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('generation_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('source_code', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('strategy', sa.String(length=100), nullable=False, server_default='general'),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('expected_improvement', sa.Text(), nullable=True),
        sa.Column('potential_risks', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('validation_passed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('validation_errors', sa.JSON(), nullable=True),
        sa.Column('tests_passed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('test_results_json', sa.JSON(), nullable=True),
        sa.Column('benchmark_results_json', sa.JSON(), nullable=True),
        sa.Column('median_time', sa.Float(), nullable=True),
        sa.Column('peak_memory', sa.Integer(), nullable=True),
        sa.Column('fitness_score', sa.Float(), nullable=True),
        sa.Column('fitness_components', sa.JSON(), nullable=True),
        sa.Column('speed_improvement', sa.Float(), nullable=True),
        sa.Column('memory_improvement', sa.Float(), nullable=True),
        sa.Column('is_eligible', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 9. source_diffs table
    op.create_table(
        'source_diffs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('experiment_id', sa.String(length=36), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('candidate_id', sa.String(length=36), sa.ForeignKey('mutation_candidates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('diff_text', sa.Text(), nullable=False),
        sa.Column('files_changed', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('lines_added', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lines_removed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('functions_modified', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 10. memory_records table
    op.create_table(
        'memory_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('memory_type', sa.String(length=50), nullable=False),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('experiment_id', sa.String(length=36), nullable=True),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='python'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 11. ai_usage_records table
    op.create_table(
        'ai_usage_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('experiment_id', sa.String(length=36), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 12. optimization_certificates table
    op.create_table(
        'optimization_certificates',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('experiment_id', sa.String(length=36), nullable=False),
        sa.Column('candidate_id', sa.String(length=36), nullable=False),
        sa.Column('original_hash', sa.String(length=64), nullable=False),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('certificate_data', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    # 13. audit_events table
    op.create_table(
        'audit_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=True),
        sa.Column('entity_id', sa.String(length=36), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('correlation_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )


def downgrade() -> None:
    for tbl in [
        'audit_events', 'optimization_certificates', 'ai_usage_records',
        'memory_records', 'source_diffs', 'mutation_candidates',
        'experiment_generations', 'experiments', 'code_versions',
        'project_files', 'projects', 'refresh_tokens', 'users',
    ]:
        op.drop_table(tbl, if_exists=True)
