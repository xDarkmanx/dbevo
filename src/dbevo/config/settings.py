# config/settings.py
# -*- coding: utf-8 -*-
"""
dbevo configuration settings.

Loaded from .dbevo.toml file in project root.

Priority (highest to lowest):
    1. CLI arguments (passed to Settings.load())
    2. .dbevo.toml file (in current dir or parents)
    3. Default values in code
"""

import tomllib  # Python 3.11+
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============================================================================
# Helper: Find .dbevo.toml in current dir or parents (simple search)
# ============================================================================

def _find_config_simple() -> Path | None:
    """
    Find .dbevo.toml by walking up from cwd.

    Simple search: cwd → parent → grandparent (max 3 levels).
    No magic markers (pyproject.toml, .git).
    """
    current = Path.cwd()

    # Check cwd + up to 2 parent levels
    for parent in [current, *list(current.parents)[:2]]:
        config = parent / '.dbevo.toml'
        if config.exists():
            return config.resolve()

    return None


# ============================================================================
# Helper: Flatten TOML [dbevo] section to flat dict
# ============================================================================

def _flatten_dbevo_config(toml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten [dbevo] TOML section to flat dict for Pydantic Settings."""
    result = {}
    dbevo = toml_data.get("dbevo", {})

    # [dbevo] → top-level
    for key, value in dbevo.items():
        if isinstance(value, dict):
            continue
        result[key] = value

    # [dbevo.database] → keys already have database_* prefix
    for key, value in dbevo.get("database", {}).items():
        result[key] = value

    # [dbevo.migrations] → add migrations_* prefix
    for key, value in dbevo.get("migrations", {}).items():
        result[f"migrations_{key}"] = value

    # [dbevo.generate] → keys as-is, handle exclude separately
    gen = dbevo.get("generate", {})
    for key, value in gen.items():
        if key == "exclude":
            for exc_key, exc_value in gen.get("exclude", {}).items():
                result[f"exclude_{exc_key}"] = exc_value
        elif key != "schemas":
            result[key] = value

    return result


# ============================================================================
# Main Settings class
# ============================================================================

class Settings(BaseSettings):
    """dbevo main configuration with TOML support."""

    model_config = SettingsConfigDict(
        # 🔹 No env_prefix — only TOML + CLI
        extra="ignore",
        case_sensitive=False,
    )

    # Global settings [dbevo]
    author: str = Field(default="", description="Author name for migration headers")
    project: str = Field(default="dbevo", description="Project name")
    auto_apply: bool = Field(default=False, description="Auto-apply migrations on startup")
    dry_run: bool = Field(default=False, description="Show SQL without executing")
    verbose: bool = Field(default=True, description="Verbose output")

    # Database [dbevo.database]
    database_uri: str = Field(..., description="PostgreSQL connection URI")

    # Migrations [dbevo.migrations]
    migrations_path: Path = Field(default=Path("dbevo"), description="Path to migrations directory")
    migrations_table: str = Field(default="dbevo.migrations")
    migrations_groups_table: str = Field(default="dbevo.migration_groups")
    migrations_history_table: str = Field(default="dbevo.migration_history")
    migrations_lock_table: str = Field(default="dbevo.locks")
    migrations_config_table: str = Field(default="dbevo.config")

    # Generate [dbevo.generate]
    migration_template: Path = Field(default=Path("templates/migration.sql.j2"))
    sqlalchemy_template: Path = Field(default=Path("templates/sqlalchemy.py.j2"))
    pydantic_template: Path = Field(default=Path("templates/pydantic.py.j2"))

    # Exclude settings
    exclude_columns: Optional[List[str]] = Field(default=None)
    exclude_technical: bool = Field(default=False)
    exclude_sensitive: bool = Field(default=False)
    exclude_foreign_keys: bool = Field(default=False)

    # Validators
    @field_validator("database_uri")
    @classmethod
    def validate_database_uri(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("database_uri must start with postgresql://")
        return v

    # Helpers for generation
    def get_exclude_list(self) -> List[str]:
        """Build final exclude list: columns + presets."""
        result = set(self.exclude_columns or [])
        if self.exclude_technical:
            result.update(["id", "create_at", "update_at"])
        if self.exclude_sensitive:
            result.update(["*_passwd", "*_hash", "*_token", "*_secret"])
        if self.exclude_foreign_keys:
            result.add("*_id")
        return list(result)

    def get_exclude_for_schema(self, schema: str) -> List[str]:
        """Get exclude list for specific schema."""
        return self.get_exclude_list()

    # Class methods for loading
    @classmethod
    def load(
        cls,
        config_path: Optional[Path] = None,
        database_uri: Optional[str] = None,
        **cli_overrides,
    ) -> "Settings":
        """Load settings from .dbevo.toml with CLI overrides."""
        data = {}

        # Auto-find config if not provided (simple search)
        if config_path is None:
            config_path = _find_config_simple()

        # Load from TOML if found
        if config_path and config_path.exists():
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)
            data.update(_flatten_dbevo_config(toml_data))

        # CLI overrides take precedence
        if database_uri:
            data["database_uri"] = database_uri
        data.update(cli_overrides)

        return cls(**data)


# ============================================================================
# Global settings instance
# ============================================================================
_settings: Optional[Settings] = None


def get_settings(config_path: Optional[Path] = None, **kwargs) -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.load(config_path=config_path, **kwargs)
    return _settings


def reset_settings() -> None:
    """Reset settings instance (useful for testing)."""
    global _settings
    _settings = None
