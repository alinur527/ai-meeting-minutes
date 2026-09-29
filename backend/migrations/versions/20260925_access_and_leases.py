"""Owner access, sessions and fenced worker leases; legacy owners remain unassigned."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_access_leases"
down_revision = "343522380fa7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table("rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False))
    op.create_table("worker_heartbeats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("meetings", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_meetings_owner_id_users", "meetings", "users", ["owner_id"], ["id"])
    op.create_index("ix_meetings_owner_id", "meetings", ["owner_id"])
    op.add_column("meetings", sa.Column("processing_mode", sa.String(32), nullable=True))
    op.add_column("meetings", sa.Column("processing_stage", sa.String(32), nullable=False, server_default="queued"))
    op.add_column("meetings", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("claim_token", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_jobs_lease_until", "jobs", ["lease_until"])
    op.create_index("ix_jobs_run_after", "jobs", ["run_after"])
    # A previously running job has no lease. It becomes recoverable, not silently discarded.
    op.execute("UPDATE jobs SET lease_until = CURRENT_TIMESTAMP WHERE status = 'running'")
    op.execute("UPDATE meetings SET processing_stage = status")


def downgrade():
    # Downgrading access control intentionally requires an operator-maintained backup restore.
    raise RuntimeError("Restore a pre-migration backup; removing ownership would reopen private data")
