import os
import subprocess
import sys
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_ADMIN_URL"), reason="requires isolated PostgreSQL"
)
def test_existing_database_upgrade_preserves_protocol():
    admin_url = make_url(os.environ["TEST_POSTGRES_ADMIN_URL"])
    name = "alem_test_migration_" + uuid4().hex
    url = admin_url.set(database=name)
    env = dict(os.environ, DATABASE_URL=url.render_as_string(hide_password=False))
    with psycopg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    ) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "343522380fa7"],
                env=env,
                check=True,
            )
            with psycopg.connect(
                url.set(drivername="postgresql").render_as_string(hide_password=False),
                autocommit=True,
            ) as db:
                meeting, participant, speaker, segment, item, job = [
                    uuid4() for _ in range(6)
                ]
                db.execute(
                    "INSERT INTO meetings(id,title,started_at,timezone,status,summary,confirmed_at,audio_path) VALUES(%s,'Сохранённый протокол',now(),'Asia/Qyzylorda','completed','Ручные правки',now(),'/data/audio/legacy.wav')",
                    (meeting,),
                )
                db.execute(
                    "INSERT INTO participants(id,meeting_id,name) VALUES(%s,%s,'Әлия')",
                    (participant, meeting),
                )
                db.execute(
                    "INSERT INTO speakers(id,meeting_id,label,participant_id) VALUES(%s,%s,'SPEAKER_00',%s)",
                    (speaker, meeting, participant),
                )
                db.execute(
                    "INSERT INTO segments(id,meeting_id,speaker_id,segment_index,start_ms,end_ms,text) VALUES(%s,%s,%s,0,0,1000,'Ертең есеп дайындаймын')",
                    (segment, meeting, speaker),
                )
                db.execute(
                    "INSERT INTO action_items(id,meeting_id,text,assignee_id,due_date,deadline_text) VALUES(%s,%s,'Отчёт',%s,'2026-09-26','ертең')",
                    (item, meeting, participant),
                )
                db.execute(
                    "INSERT INTO action_item_sources VALUES(%s,%s)", (item, segment)
                )
                db.execute(
                    "INSERT INTO jobs(id,meeting_id,status,attempts) VALUES(%s,%s,'running',1)",
                    (job, meeting),
                )
                tables = [
                    "meetings",
                    "participants",
                    "speakers",
                    "segments",
                    "action_items",
                    "action_item_sources",
                    "jobs",
                ]
                before = {}
                for table in tables:
                    cursor = db.execute(
                        sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
                    )
                    before[table] = (
                        [column.name for column in cursor.description],
                        cursor.fetchall(),
                    )
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    env=env,
                    check=True,
                )
                for table, (columns, rows) in before.items():
                    query = sql.SQL("SELECT {} FROM {}").format(
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.Identifier(table),
                    )
                    assert db.execute(query).fetchall() == rows
                assert db.execute(
                    "SELECT owner_id,processing_stage FROM meetings"
                ).fetchone() == (None, "completed")
                assert db.execute("SELECT lease_until <= now() FROM jobs").fetchone()[0]
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
