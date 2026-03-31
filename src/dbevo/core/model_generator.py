# core/model_generator.py
# -*- coding: utf-8 -*-
"""Model generation using Jinja2 templates."""

import re

from pathlib import Path
from datetime import datetime
from typing import Optional, List
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .introspector import DatabaseIntrospector

def find_project_root(start_path: Path | None = None) -> Path:
    """Find project root by looking for markers."""
    current = start_path or Path.cwd()

    for parent in [current, *current.parents]:
        if (parent / 'pyproject.toml').exists():
            return parent.resolve()
        if (parent / '.git').exists():
            return parent.resolve()
        if (parent / '.dbevo.toml').exists():
            return parent.resolve()

    return current.resolve()

class ModelGenerator:
    """Generate SQLAlchemy/Pydantic models from database schema."""

    def __init__(
        self,
        database_uri: str,
        template_dir: Path,
        output_dir: Path,
        exclude_columns: Optional[List[str]] = None,
        exclude_technical: bool = False,
        exclude_sensitive: bool = False,
    ):
        self.database_uri = database_uri
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.exclude_columns = exclude_columns or []
        self.exclude_technical = exclude_technical
        self.exclude_sensitive = exclude_sensitive
        self.project_root = find_project_root()  # ← Находим корень проекта

        # Setup Jinja2
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['py', 'jinja2']),
            trim_blocks=False,  # ← Сохраняем переносы
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )

        self.introspector = DatabaseIntrospector(database_uri)

    def _should_exclude(self, column_name: str) -> bool:
        """Check if column should be excluded."""
        if column_name in self.exclude_columns:
            return True

        for pattern in self.exclude_columns:
            if '*' in pattern:
                if re.match(pattern.replace('*', '.*'), column_name):
                    return True

        if self.exclude_technical and column_name in ('id', 'create_at', 'update_at'):
            return True

        if self.exclude_sensitive:
            sensitive_patterns = ['*_passwd', '*_password', '*_hash', '*_token', '*_secret']
            for pattern in sensitive_patterns:
                if re.match(pattern.replace('*', '.*'), column_name):
                    return True

        return False

    def _to_class_name(self, table_name: str) -> str:
        """Convert table_name to ClassName."""
        parts = [p.capitalize() for p in table_name.split('_') if p]
        return ''.join(parts) or 'Model'

    def _relative_path(self, file_path: Path) -> str:
        """Get relative path from project root."""
        try:
            return str(file_path.relative_to(self.project_root))
        except ValueError:
            # Если файл не в проекте, возвращаем абсолютный
            return str(file_path)

    async def generate(
        self,
        schema: str,
        template_name: str = 'sqlalchemy.py.j2',
        tables: Optional[List[str]] = None,
    ) -> List[Path]:
        """Generate models for schema."""

        # Load template
        template = self.jinja_env.get_template(template_name)

        # Get tables from DB
        await self.introspector.connect()
        db_tables = await self.introspector.get_tables(schema)

        # Filter if specific tables requested
        if tables:
            db_tables = [t for t in db_tables if t['name'] in tables]

        generated = []

        for table_info in db_tables:
            # Filter excluded columns
            columns = [
                col for col in table_info['columns']
                if not self._should_exclude(col['name'])
            ]

            # Skip if all columns excluded
            if not columns:
                continue

            # Class name
            class_name = self._to_class_name(table_info['name'])

            # Output file path
            output_file = self.output_dir / f"{class_name}.py"

            # 🔹 Relative path from project root
            output_path = self._relative_path(output_file)

            # Prepare context
            context = {
                'schema_name': schema,
                'table_name': table_info['name'],
                'class_name': class_name,
                'columns': columns,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'output_path': output_path,
            }

            # Render template
            content = template.render(**context)

            # Write file
            output_file = self.output_dir / f"{context['class_name']}.py"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content, encoding='utf-8')

            generated.append(output_file)

        await self.introspector.close()
        return generated
