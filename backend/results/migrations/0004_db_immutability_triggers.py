"""Database-layer immutability for the results audit trail.

The model ``save()``/``delete()`` guards in ``results.models`` stop *ORM* writes,
but ``QuerySet.update()``, ``bulk_update()`` and raw SQL bypass them. These
PostgreSQL triggers move the guarantee down to the database so no code path —
ORM or otherwise — can rewrite append-only history:

* ``results_student_score`` — a row on a RATIFIED_BY_SENATE result, or any
  superseded row (``is_current = false``), may not have its value columns
  (ca_score, exam_score, total, grade) changed, and may not be deleted. Changing
  only ``is_current``/``updated_at`` stays allowed, which is exactly what the
  amendment supersession path does.
* ``results_audit_log`` — no UPDATE or DELETE at all (append-only).

Triggers are PostgreSQL-specific. On any other backend (e.g. SQLite) this
migration is a no-op, so the immutability is enforced only where the app
actually runs in production. Tests that assert the trigger behaviour are
skipped off PostgreSQL rather than giving false confidence.
"""

from django.db import connection, migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION results_protect_student_score() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status FROM results_course_result WHERE id = OLD.result_id;

    IF (TG_OP = 'DELETE') THEN
        IF (v_status = 'ratified_by_senate' OR OLD.is_current = false) THEN
            RAISE EXCEPTION
                'StudentScore % is immutable: cannot DELETE a superseded row or a row on a ratified result',
                OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    -- UPDATE: block changes to value columns; allow currency/timestamp flips.
    IF (v_status = 'ratified_by_senate' OR OLD.is_current = false) THEN
        IF (NEW.ca_score IS DISTINCT FROM OLD.ca_score
            OR NEW.exam_score IS DISTINCT FROM OLD.exam_score
            OR NEW.total IS DISTINCT FROM OLD.total
            OR NEW.grade IS DISTINCT FROM OLD.grade) THEN
            RAISE EXCEPTION
                'StudentScore % is immutable: value columns cannot change on a superseded row or a row on a ratified result',
                OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS results_student_score_immutability ON results_student_score;
CREATE TRIGGER results_student_score_immutability
    BEFORE UPDATE OR DELETE ON results_student_score
    FOR EACH ROW EXECUTE FUNCTION results_protect_student_score();

CREATE OR REPLACE FUNCTION results_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'results_audit_log is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS results_audit_log_no_mutation ON results_audit_log;
CREATE TRIGGER results_audit_log_no_mutation
    BEFORE UPDATE OR DELETE ON results_audit_log
    FOR EACH ROW EXECUTE FUNCTION results_audit_log_append_only();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS results_student_score_immutability ON results_student_score;
DROP FUNCTION IF EXISTS results_protect_student_score();
DROP TRIGGER IF EXISTS results_audit_log_no_mutation ON results_audit_log;
DROP FUNCTION IF EXISTS results_audit_log_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("results", "0003_alter_resultauditlog_action"),
    ]

    # The triggers are PostgreSQL DDL. On other backends the migration records
    # as applied but installs nothing, so the rest of the suite still runs.
    if connection.vendor == "postgresql":
        operations = [migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL)]
    else:
        operations = []
