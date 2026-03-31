------------------------------------------------------------------------------------------------------------------------
-- Author: Semenets Pavel <p.semenets@gmail.com>
-- Project: dbevo
-- Schema: core
-- Create: Date: 2026-03-31
-- Migration: 000004__create_projects_table
------------------------------------------------------------------------------------------------------------------------

-- !Ups
------------------------------------------------------------------------------------------------------------------------
-- Desc: create_projects_table
------------------------------------------------------------------------------------------------------------------------
CREATE SEQUENCE "core"."projects_id_seq" INCREMENT 1 START 1;
CREATE TABLE "core"."projects" (
   "id"                       INTEGER NOT NULL DEFAULT nextval('core.projects_id_seq'::REGCLASS)
  ,"create_at"                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
  ,"update_at"                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
  ,"cp_lkey"                  INTEGER NOT NULL DEFAULT 1
  ,"cp_rkey"                  INTEGER NOT NULL DEFAULT 2
  ,"cp_lvl"                   INTEGER NOT NULL DEFAULT 0
  ,"cp_meta"                  JSONB NOT NULL
  ,"cp_enable"                BOOLEAN NOT NULL DEFAULT TRUE
  ,PRIMARY KEY ("id")
);
ALTER SEQUENCE "core"."projects_id_seq" OWNED BY "core"."projects"."id";
CREATE TRIGGER "core_projects_update_tr" BEFORE UPDATE ON "core"."projects" FOR EACH ROW EXECUTE PROCEDURE "utils"."tbl_update_ftr"();

------------------------------------------------------------------------------------------------------------------------
-- Desc: Comments
------------------------------------------------------------------------------------------------------------------------
COMMENT ON TABLE "core"."projects" IS 'Registered projects';
COMMENT ON COLUMN "core"."projects"."id" IS 'Primary Key (Sequence)';
COMMENT ON COLUMN "core"."projects"."create_at" IS 'Record create date';
COMMENT ON COLUMN "core"."projects"."update_at" IS 'Record update date';
COMMENT ON COLUMN "core"."projects"."cp_lkey" IS 'Record left key (Nested Sets)';
COMMENT ON COLUMN "core"."projects"."cp_rkey" IS 'Record right key (Nested Sets)';
COMMENT ON COLUMN "core"."projects"."cp_lvl" IS 'Record level (Nested Sets)';
COMMENT ON COLUMN "core"."projects"."cp_meta" IS 'Projects Information';
COMMENT ON COLUMN "core"."projects"."cp_enable" IS 'Enable|Disable projects';


-- !Ups end

-- !Downs
------------------------------------------------------------------------------------------------------------------------
-- Desc: Rollback
------------------------------------------------------------------------------------------------------------------------
DROP TABLE IF EXISTS "core"."projects" CASCADE;

-- !Downs end
