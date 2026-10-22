"""Anonymous school feedback, without user identity or request metadata.

Revision ID: 0025_survey
Revises: 0024
"""
from alembic import op

revision = "0025_survey"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE survey_responses (
 submission_id uuid PRIMARY KEY,
 version varchar(64) NOT NULL CHECK (version='guguta-schools-2026-v1'),
 submitted_on date NOT NULL DEFAULT CURRENT_DATE,
 answers jsonb NOT NULL CHECK (jsonb_typeof(answers)='object' AND octet_length(answers::text)<=16000)
);
ALTER TABLE survey_responses ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON survey_responses FROM PUBLIC, guguta_api, guguta_worker;
CREATE INDEX ix_survey_version ON survey_responses(version);

CREATE FUNCTION guguta_survey_submit(p_id uuid, p_version text, p_answers jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF jsonb_typeof(p_answers)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_answers))<>20 THEN
  RAISE EXCEPTION 'invalid questionnaire';
 END IF;
 INSERT INTO survey_responses(submission_id,version,answers) VALUES(p_id,p_version,p_answers)
 ON CONFLICT(submission_id) DO NOTHING;
END; $$;

CREATE FUNCTION guguta_survey_counts(p_version text)
RETURNS TABLE(question text,answer text,responses bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT '__total__'::text,''::text,count(*) FROM survey_responses WHERE version=p_version
 UNION ALL
 SELECT entry.key, CASE WHEN entry.key IN ('q19','q20') THEN '__written__' ELSE choice.value END, count(*)
 FROM survey_responses r
 CROSS JOIN LATERAL jsonb_each(r.answers) entry
 CROSS JOIN LATERAL jsonb_array_elements_text(CASE WHEN jsonb_typeof(entry.value)='array'
   THEN entry.value ELSE jsonb_build_array(entry.value) END) choice
 WHERE r.version=p_version AND choice.value<>''
 GROUP BY entry.key, CASE WHEN entry.key IN ('q19','q20') THEN '__written__' ELSE choice.value END;
$$;

CREATE FUNCTION guguta_survey_comments(p_version text,p_question text,p_offset integer,p_limit integer)
RETURNS TABLE(answer text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT answers->>p_question FROM survey_responses
 WHERE version=p_version AND p_question IN ('q19','q20') AND coalesce(answers->>p_question,'')<>''
 ORDER BY submitted_on,submission_id
 OFFSET greatest(0,p_offset) LIMIT least(greatest(1,p_limit),50);
$$;

REVOKE ALL ON FUNCTION guguta_survey_submit(uuid,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION guguta_survey_counts(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION guguta_survey_comments(text,text,integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION guguta_survey_submit(uuid,text,jsonb) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_survey_counts(text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_survey_comments(text,text,integer,integer) TO guguta_api;
""")


def downgrade() -> None:
    op.execute("""
DROP FUNCTION guguta_survey_comments(text,text,integer,integer);
DROP FUNCTION guguta_survey_counts(text);
DROP FUNCTION guguta_survey_submit(uuid,text,jsonb);
DROP TABLE survey_responses;
""")
