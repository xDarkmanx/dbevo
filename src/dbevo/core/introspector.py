# core/introspector.py
# -*- coding: utf-8 -*-
"""Database schema introspection for PostgreSQL."""

import asyncpg
from typing import Optional


class DatabaseIntrospector:
    """Introspect PostgreSQL database schema."""

    def __init__(self, database_uri: str):
        self.database_uri = database_uri
        self._connection: Optional[asyncpg.Connection] = None

    async def connect(self) -> None:
        """Establish database connection."""
        self._connection = await asyncpg.connect(self.database_uri)

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def get_tables(self, schema: str) -> list[dict]:
        """Get list of tables in schema with columns."""
        if not self._connection:
            await self.connect()

        # Get tables
        tables_query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        rows = await self._connection.fetch(tables_query, schema)
        tables = [row['table_name'] for row in rows]

        # Get columns for each table
        result = []
        for table_name in tables:
            columns = await self._get_columns(schema, table_name)
            result.append({
                'name': table_name,
                'columns': columns,
            })

        return result

    async def _get_columns(self, schema: str, table: str) -> list[dict]:
        """Get columns for a table with type mapping and comments."""
        if not self._connection:
            await self.connect()

        query = """
            SELECT
                c.column_name,
                c.data_type,
                c.character_maximum_length,
                c.is_nullable,
                c.column_default,
                d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_class pc
                ON pc.relname = c.table_name
                AND pc.relnamespace = (
                    SELECT oid FROM pg_catalog.pg_namespace
                    WHERE nspname = c.table_schema
                )
            LEFT JOIN pg_catalog.pg_attribute pa
                ON pa.attrelid = pc.oid
                AND pa.attname = c.column_name
            LEFT JOIN pg_catalog.pg_description d
                ON d.objoid = pc.oid
                AND d.objsubid = pa.attnum
            WHERE c.table_schema = $1
            AND c.table_name = $2
            ORDER BY c.ordinal_position
        """
        rows = await self._connection.fetch(query, schema, table)

        columns = []
        for row in rows:
            pg_type = row['data_type'].lower()
            type_name = self._map_type(pg_type)
            python_type = self._map_python_type(pg_type)  # ← ← ← ДОБАВЛЯЕМ!

            length = row['character_maximum_length']
            if type_name not in ('varchar', 'character varying', 'character', 'char'):
                length = None

            default = self._parse_default(row['column_default'], pg_type)

            columns.append({
                'name': row['column_name'],
                'type_name': type_name,        # Для SQLAlchemy (INTEGER, JSONB)
                'python_type': python_type,    # Для Pydantic (int, str, datetime) ← ← ←
                'length': length,
                'nullable': row['is_nullable'] == 'YES',
                'default': default,
                'comment': row['column_comment'] or '',
                'pg_type': pg_type,
            })

        return columns

    def _map_type(self, pg_type: str) -> str:
        """Map PostgreSQL type to SQLAlchemy type name (for psql.*)."""
        mapping = {
            # Integer
            'integer': 'INTEGER',
            'bigint': 'BIGINT',
            'smallint': 'SMALLINT',
            'serial': 'INTEGER',
            'bigserial': 'BIGINT',

            # String
            'character varying': 'VARCHAR',
            'varchar': 'VARCHAR',
            'character': 'CHAR',
            'char': 'CHAR',
            'text': 'TEXT',
            'citext': 'CITEXT',

            # Boolean
            'boolean': 'BOOLEAN',

            # Date/Time
            'date': 'DATE',
            'time': 'TIME',
            'time without time zone': 'TIME',
            'time with time zone': 'TIME',
            'timestamp': 'TIMESTAMP',
            'timestamp without time zone': 'TIMESTAMP',
            'timestamp with time zone': 'TIMESTAMP',
            'interval': 'INTERVAL',

            # Numeric
            'real': 'REAL',
            'double precision': 'DOUBLE_PRECISION',
            'numeric': 'NUMERIC',
            'decimal': 'NUMERIC',
            'money': 'MONEY',

            # JSON
            'json': 'JSON',
            'jsonb': 'JSONB',

            # UUID
            'uuid': 'UUID',

            # Network
            'inet': 'INET',
            'cidr': 'CIDR',
            'macaddr': 'MACADDR',

            # Binary
            'bytea': 'BYTEA',

            # Arrays
            'array': 'ARRAY',

            # Other
            'oid': 'OID',
            'regclass': 'REGCLASS',
            'hstore': 'HSTORE',
            'enum': 'ENUM',
        }
        return mapping.get(pg_type, 'TEXT')

    def _map_python_type(self, pg_type: str) -> str:
        """Map PostgreSQL type to Python type for Pydantic."""
        mapping = {
            # Integer
            'integer': 'int',
            'bigint': 'int',
            'smallint': 'int',
            'serial': 'int',
            'bigserial': 'int',

            # String
            'character varying': 'str',
            'varchar': 'str',
            'character': 'str',
            'char': 'str',
            'text': 'str',
            'citext': 'str',

            # Boolean
            'boolean': 'bool',

            # Date/Time
            'date': 'date',
            'time': 'time',
            'time without time zone': 'time',
            'time with time zone': 'time',
            'timestamp': 'datetime',
            'timestamp without time zone': 'datetime',
            'timestamp with time zone': 'datetime',
            'interval': 'timedelta',

            # Numeric
            'real': 'float',
            'double precision': 'float',
            'numeric': 'Decimal',
            'decimal': 'Decimal',
            'money': 'Decimal',

            # JSON
            'json': 'Dict[str, Any]',
            'jsonb': 'Dict[str, Any]',

            # UUID
            'uuid': 'UUID',

            # Binary
            'bytea': 'bytes',

            # Arrays
            'array': 'List[Any]',

            # Other
            'oid': 'int',
            'regclass': 'str',
            'hstore': 'Dict[str, str]',
            'enum': 'str',
        }
        return mapping.get(pg_type, 'str')

    def _parse_default(self, default: Optional[str], pg_type: str) -> Optional[str]:
        """Parse column default value to SQLAlchemy representation."""
        if default is None:
            return None

        default = default.strip()

        # Sequence defaults (SERIAL, IDENTITY) — игнорируем
        if 'nextval' in default.lower():
            return None

        # Функции (now(), gen_random_uuid(), etc.) — оставляем как есть
        if '(' in default and not default.startswith("'"):
            return default

        # Boolean
        if pg_type == 'boolean':
            if default.lower() in ('true', "'true'"):
                return 'True'
            elif default.lower() in ('false', "'false'"):
                return 'False'
            return None

        # String literals — оставляем кавычки для SQLAlchemy
        if default.startswith("'") and default.endswith("'"):
            return default  # e.g., "'{}'" for JSONB

        # 🔹 Integer — ТЕПЕРЬ РАЗРЕШАЕМ числовые дефолты
        # Для nested sets и других случаев это могут быть реальные дефолты
        if pg_type in ('integer', 'bigint', 'smallint', 'int', 'int4', 'int8'):
            # Простое число — возвращаем как есть
            if default.isdigit() or (default.startswith('-') and default[1:].isdigit()):
                return default  # ← Теперь возвращаем, а не None!
            return default

        # Numeric с точкой
        if pg_type in ('numeric', 'decimal', 'real', 'double precision'):
            try:
                float(default.replace(',', '.'))
                return default.replace(',', '.')
            except ValueError:
                return None

        # Всё остальное — пропускаем (безопаснее)
        return None
