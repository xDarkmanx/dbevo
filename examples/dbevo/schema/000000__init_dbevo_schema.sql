-- 000000__init_dbevo_schema.sql
------------------------------------------------------------------------------------------------------------------------
-- Author: Semenets Pavel <p.semenets@gmail.com>
-- Project: dbevo
-- Schema: dbevo
-- Create: Date: 2026-03-30
-- Migration: 000000__init_dbevo_schema
------------------------------------------------------------------------------------------------------------------------

-- !Ups
------------------------------------------------------------------------------------------------------------------------
-- Desc: Create dbevo schema and tracking tables
------------------------------------------------------------------------------------------------------------------------

-- Создаём схему
CREATE SCHEMA IF NOT EXISTS "dbevo";
COMMENT ON SCHEMA "dbevo" IS 'dbevo migration tracking schema';

-------------------------------------------------------------------------------
-- Таблица 1: "migration_groups" (справочник групп)
-------------------------------------------------------------------------------
CREATE SEQUENCE "dbevo"."migration_groups_id_seq" INCREMENT 1 START 1;
CREATE TABLE "dbevo"."migration_groups" (
     "id"              BIGINT NOT NULL DEFAULT nextval('dbevo.migration_groups_id_seq'::REGCLASS)
    ,"created_at"      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"updated_at"      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"name"            CHARACTER VARYING(128) UNIQUE NOT NULL
    ,"description"     CHARACTER VARYING(255)
    ,"is_enabled"      BOOLEAN NOT NULL DEFAULT TRUE
    ,PRIMARY KEY ("id")
);
ALTER SEQUENCE "dbevo"."migration_groups_id_seq" OWNED BY "dbevo"."migration_groups"."id";

CREATE INDEX idx_migration_groups_name ON "dbevo"."migration_groups"(name);
CREATE INDEX idx_migration_groups_enabled ON "dbevo"."migration_groups"(is_enabled);

COMMENT ON TABLE "dbevo"."migration_groups" IS 'Migration groups/schemas registry';
COMMENT ON COLUMN "dbevo"."migration_groups"."id" IS 'Primary Key (Sequence)';
COMMENT ON COLUMN "dbevo"."migration_groups"."created_at" IS 'Record create date';
COMMENT ON COLUMN "dbevo"."migration_groups"."updated_at" IS 'Record update date (auto-updated by trigger)';
COMMENT ON COLUMN "dbevo"."migration_groups"."name" IS 'Group name (e.g., core, utils, analytics)';
COMMENT ON COLUMN "dbevo"."migration_groups"."description" IS 'Human-readable description of the group';
COMMENT ON COLUMN "dbevo"."migration_groups"."is_enabled" IS 'Enable|Disable group migrations';


-------------------------------------------------------------------------------
-- Таблица 2: migrations (применённые миграции)
-------------------------------------------------------------------------------
CREATE SEQUENCE "dbevo"."migrations_id_seq" INCREMENT 1 START 1;
CREATE TABLE "dbevo"."migrations" (
     "id"                  BIGINT NOT NULL DEFAULT nextval('dbevo.migrations_id_seq'::REGCLASS)
    ,"applied_at"          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"applied_by"          CHARACTER VARYING(255)
    ,"group_id"            BIGINT NOT NULL REFERENCES "dbevo"."migration_groups"(id) ON DELETE CASCADE
    ,"migration_number"    INTEGER NOT NULL
    ,"migration_hash"      CHAR(64) NOT NULL
    ,"description"         CHARACTER VARYING(255)
    ,"status"              CHARACTER VARYING(50) NOT NULL DEFAULT 'applied'
    ,"execution_time_ms"   INTEGER
    ,PRIMARY KEY ("id")
    ,UNIQUE ("group_id", "migration_number")
);
ALTER SEQUENCE "dbevo"."migrations_id_seq" OWNED BY "dbevo"."migrations"."id";

CREATE INDEX "idx_migrations_group" ON "dbevo"."migrations"(group_id);
CREATE INDEX "idx_migrations_status" ON "dbevo"."migrations"(status);
CREATE INDEX "idx_migrations_applied_at" ON "dbevo"."migrations"(applied_at);

COMMENT ON TABLE "dbevo"."migrations" IS 'Current state of applied migrations';
COMMENT ON COLUMN "dbevo"."migrations"."id" IS 'Primary Key (Sequence)';
COMMENT ON COLUMN "dbevo"."migrations"."applied_at" IS 'When migration was applied';
COMMENT ON COLUMN "dbevo"."migrations"."applied_by" IS 'Who applied migration (from config)';
COMMENT ON COLUMN "dbevo"."migrations"."group_id" IS 'Foreign Key to migration_groups.id';
COMMENT ON COLUMN "dbevo"."migrations"."migration_number" IS 'Migration number from filename (000001, 000002...)';
COMMENT ON COLUMN "dbevo"."migrations"."migration_hash" IS 'SHA-256 hash of !Ups section (detects changes)';
COMMENT ON COLUMN "dbevo"."migrations"."description" IS 'Migration description from filename';
COMMENT ON COLUMN "dbevo"."migrations"."status" IS 'Migration status (applied, reverted, failed)';
COMMENT ON COLUMN "dbevo"."migrations"."execution_time_ms" IS 'Execution time in milliseconds';

-------------------------------------------------------------------------------
-- Таблица 3: migration_history (полный аудит)
-------------------------------------------------------------------------------
CREATE SEQUENCE "dbevo"."migration_history_id_seq" INCREMENT 1 START 1;
CREATE TABLE "dbevo"."migration_history" (
     "id"                  BIGINT NOT NULL DEFAULT nextval('dbevo.migration_history_id_seq'::REGCLASS)
    ,"executed_at"         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"executed_by"         CHARACTER VARYING(255)
    ,"group_id"            BIGINT NOT NULL REFERENCES "dbevo"."migration_groups"(id) ON DELETE CASCADE
    ,"migration_number"    INTEGER NOT NULL
    ,"action"              CHARACTER VARYING(50) NOT NULL
    ,"previous_hash"       CHAR(64)
    ,"new_hash"            CHAR(64)
    ,"execution_time_ms"   INTEGER
    ,"error_message"       TEXT
    ,PRIMARY KEY ("id")
);
ALTER SEQUENCE "dbevo"."migration_history_id_seq" OWNED BY "dbevo"."migration_history"."id";

CREATE INDEX "idx_history_group" ON "dbevo"."migration_history"(group_id);
CREATE INDEX "idx_history_action" ON "dbevo"."migration_history"(action);
CREATE INDEX "idx_history_executed_at" ON "dbevo"."migration_history"(executed_at);

COMMENT ON TABLE "dbevo"."migration_history" IS 'Full audit log of all migration operations (stored forever)';
COMMENT ON COLUMN "dbevo"."migration_history"."id" IS 'Primary Key (Sequence)';
COMMENT ON COLUMN "dbevo"."migration_history"."executed_at" IS 'When action was executed';
COMMENT ON COLUMN "dbevo"."migration_history"."executed_by" IS 'Who executed action (from config)';
COMMENT ON COLUMN "dbevo"."migration_history"."group_id" IS 'Foreign Key to migration_groups.id';
COMMENT ON COLUMN "dbevo"."migration_history"."migration_number" IS 'Migration number from filename';
COMMENT ON COLUMN "dbevo"."migration_history"."action" IS 'Action type (applied, reverted, failed)';
COMMENT ON COLUMN "dbevo"."migration_history"."previous_hash" IS 'Hash before change (for revert/modify)';
COMMENT ON COLUMN "dbevo"."migration_history"."new_hash" IS 'Hash after change';
COMMENT ON COLUMN "dbevo"."migration_history"."execution_time_ms" IS 'Execution time in milliseconds';
COMMENT ON COLUMN "dbevo"."migration_history"."error_message" IS 'Error message if action = failed';

-------------------------------------------------------------------------------
-- Таблица 4: locks (блокировки)
-------------------------------------------------------------------------------
CREATE TABLE "dbevo"."locks" (
     "expires_at"      TIMESTAMPTZ
    ,"lock_name"       CHARACTER VARYING(128)
    ,"locked_at"       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"locked_by"       CHARACTER VARYING(255) NOT NULL
    ,CONSTRAINT "check_not_expired" CHECK (expires_at IS NULL OR expires_at > NOW())
    ,PRIMARY KEY ("lock_name")
);

COMMENT ON TABLE "dbevo"."locks" IS 'Prevents concurrent migration execution';
COMMENT ON COLUMN "dbevo"."locks"."expires_at" IS 'When lock expires (NULL = no expiry)';
COMMENT ON COLUMN "dbevo"."locks"."lock_name" IS 'Lock identifier (e.g., migration_lock)';
COMMENT ON COLUMN "dbevo"."locks"."locked_at" IS 'When lock was acquired';
COMMENT ON COLUMN "dbevo"."locks"."locked_by" IS 'Who acquired lock (from config)';

-------------------------------------------------------------------------------
-- Таблица 5: config (опционально)
-------------------------------------------------------------------------------
CREATE TABLE "dbevo"."config" (
     "updated_at"      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    ,"updated_by"      CHARACTER VARYING(255)
    ,"key"             CHARACTER VARYING(128)
    ,"value"           TEXT
    ,PRIMARY KEY ("key")
);

COMMENT ON TABLE "dbevo"."config" IS 'Runtime configuration for dbevo (future use)';
COMMENT ON COLUMN "dbevo"."config"."updated_at" IS 'When config was last updated';
COMMENT ON COLUMN "dbevo"."config"."updated_by" IS 'Who updated config (from config)';
COMMENT ON COLUMN "dbevo"."config"."key" IS 'Configuration key name';
COMMENT ON COLUMN "dbevo"."config"."value" IS 'Configuration value';

-------------------------------------------------------------------------------
-- Триггер для обновления updated_at в groups
-------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "dbevo"."update_updated_at_column"()
RETURNS TRIGGER AS
$$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
$$
LANGUAGE plpgsql;

CREATE TRIGGER "trg_migration_groups_updated_at"
    BEFORE UPDATE ON "dbevo"."migration_groups"
    FOR EACH ROW
    EXECUTE FUNCTION "dbevo"."update_updated_at_column"();

COMMENT ON FUNCTION "dbevo"."update_updated_at_column"() IS 'Trigger function to auto-update updated_at column';

-- !Ups end

-- !Downs
------------------------------------------------------------------------------------------------------------------------
-- Desc: Rollback
------------------------------------------------------------------------------------------------------------------------
DROP SCHEMA IF EXISTS "dbevo" CASCADE;
-- !Downs end
