"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-02 17:46:51.569259
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('s3_object_key', sa.String(length=512), nullable=False),
    sa.Column('thumbnail_key', sa.String(length=512), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('original_filename', sa.String(length=512), nullable=True),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('annotation_status', sa.Enum('unlabeled', 'labeled', name='annotation_status', native_enum=False, length=32), nullable=False),
    sa.Column('dataset_split', sa.Enum('train', 'validation', name='dataset_split', native_enum=False, length=32), nullable=True),
    sa.Column('labeled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sha256')
    )
    op.create_index(op.f('ix_images_annotation_status'), 'images', ['annotation_status'], unique=False)
    op.create_table('model_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('status', sa.Enum('candidate', 'production', 'archived', name='model_status', native_enum=False, length=32), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('architecture', sa.String(length=64), nullable=False),
    sa.Column('checkpoint_key', sa.String(length=512), nullable=False),
    sa.Column('onnx_key', sa.String(length=512), nullable=False),
    sa.Column('openvino_key', sa.String(length=512), nullable=False),
    sa.Column('config_key', sa.String(length=512), nullable=True),
    sa.Column('input_width', sa.Integer(), nullable=False),
    sa.Column('input_height', sa.Integer(), nullable=False),
    sa.Column('class_names', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('class_mapping_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('metrics_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('dataset_snapshot', sa.String(length=256), nullable=True),
    sa.Column('training_run_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version')
    )
    op.create_index('uq_model_versions_single_production', 'model_versions', ['status'], unique=True, postgresql_where=sa.text("status = 'production'"), sqlite_where=sa.text("status = 'production'"))
    op.create_table('settings',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('training_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'completed', 'failed', name='training_status', native_enum=False, length=32), nullable=False),
    sa.Column('base_model_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_snapshot', sa.String(length=256), nullable=True),
    sa.Column('dataset_stats_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('input_width', sa.Integer(), nullable=False),
    sa.Column('input_height', sa.Integer(), nullable=False),
    sa.Column('epochs', sa.Integer(), nullable=False),
    sa.Column('batch_size', sa.Integer(), nullable=False),
    sa.Column('learning_rate', sa.Float(), nullable=True),
    sa.Column('params_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('progress_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('metrics_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('log', sa.Text(), server_default='', nullable=False),
    sa.Column('log_key', sa.String(length=512), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('job_id', sa.String(length=64), nullable=True),
    sa.Column('model_version_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_training_runs_status'), 'training_runs', ['status'], unique=False)
    # model_versions <-> training_runs reference each other: add this FK after both tables exist
    op.create_foreign_key('fk_model_versions_training_run_id', 'model_versions', 'training_runs',
                          ['training_run_id'], ['id'], ondelete='SET NULL')
    op.create_table('annotations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('class_name', sa.String(length=64), nullable=False),
    sa.Column('x1', sa.Float(), nullable=False),
    sa.Column('y1', sa.Float(), nullable=False),
    sa.Column('x2', sa.Float(), nullable=False),
    sa.Column('y2', sa.Float(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_annotations_image_id'), 'annotations', ['image_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_annotations_image_id'), table_name='annotations')
    op.drop_table('annotations')
    op.drop_index(op.f('ix_training_runs_status'), table_name='training_runs')
    op.drop_constraint('fk_model_versions_training_run_id', 'model_versions', type_='foreignkey')
    op.drop_table('training_runs')
    op.drop_table('settings')
    op.drop_index('uq_model_versions_single_production', table_name='model_versions', postgresql_where=sa.text("status = 'production'"), sqlite_where=sa.text("status = 'production'"))
    op.drop_table('model_versions')
    op.drop_index(op.f('ix_images_annotation_status'), table_name='images')
    op.drop_table('images')
