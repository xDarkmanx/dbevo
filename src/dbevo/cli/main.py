# dbevo/cli/main.py
# -*- coding: utf-8 -*-
"""
dbevo CLI - Database Evolutions for Python.

Inspired by Play Framework Evolutions.
"""

import asyncio
import click
import asyncpg
import sys

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import get_settings
from ..core import MigrationGenerator
from ..core import MigrationExecutor
from ..core import MigrationParser

console = Console()


# ==============================================================================
# Helper: Find project root and config file
# ==============================================================================

def find_project_root(start_path: Path | None = None) -> Path:
    """
    Find project root by looking for markers.

    Search order:
    1. pyproject.toml (Poetry/PEP 517 project)
    2. .git directory (VCS root)
    3. .dbevo.toml (dbevo config root)
    4. Fallback to start_path or cwd
    """
    current = start_path or Path.cwd()

    for parent in [current, *current.parents]:
        if (parent / 'pyproject.toml').exists():
            return parent.resolve()
        if (parent / '.git').exists():
            return parent.resolve()
        if (parent / '.dbevo.toml').exists():
            return parent.resolve()

    return current.resolve()


def find_config_file(project_root: Path | None = None) -> Path | None:
    """Find .dbevo.toml in project root or parents."""
    root = project_root or find_project_root()

    for parent in [root, *root.parents]:
        config = parent / '.dbevo.toml'
        if config.exists():
            return config.resolve()

    return None


def prompt_create_config(project_root: Path) -> bool:
    """Prompt user to create .dbevo.toml from example."""
    example = project_root / '.dbevo.toml.example'

    console.print("\n[bold yellow]⚠️  Configuration not found[/bold yellow]")
    console.print(f"Expected: [cyan]{project_root / '.dbevo.toml'}[/cyan]\n")

    if example.exists():
        console.print(f"Example found: [cyan]{example}[/cyan]\n")
        if click.confirm("Copy .dbevo.toml.example to .dbevo.toml?"):
            import shutil
            shutil.copy2(example, project_root / '.dbevo.toml')
            console.print(f"[green]✓[/green] Created: [cyan]{project_root / '.dbevo.toml'}[/cyan]")
            console.print("[dim]✏️  Please edit the file to configure your database connection[/dim]\n")
            return True
    else:
        console.print("[dim]No .dbevo.toml.example found. Create manually:[/dim]")
        console.print(f"  [cyan]{project_root / '.dbevo.toml'}[/cyan]\n")

    return False


def ensure_config() -> Path:
    """Ensure .dbevo.toml exists. Returns project root (cwd)."""
    project_root = Path.cwd()
    config = _find_config_simple()

    if config is None:
        console.print("\n[bold red]✗ Configuration not found[/bold red]")
        console.print("Expected: [cyan].dbevo.toml[/cyan] in current directory or parent\n")
        console.print("[dim]Create .dbevo.toml with required [dbevo.database] section:[/dim]")
        console.print("""
[dbevo]
project = "my-project"

[dbevo.database]
database_uri = "postgresql://user:pass@localhost:5432/db"
        """.strip())
        console.print()
        sys.exit(1)

    return project_root

def _find_config_simple() -> Path | None:
    """Find .dbevo.toml in current directory only."""
    config = Path.cwd() / '.dbevo.toml'
    return config if config.exists() else None

# ==============================================================================
# Decorator for --debug option
# ==============================================================================

def debug_option():
    """Decorator to add --debug option to commands."""
    def decorator(f):
        return click.option(
            "--debug",
            is_flag=True,
            default=None,
            help="Enable debug output"
        )(f)
    return decorator


def _get_debug(debug: bool | None = None) -> bool:
    """Get debug flag from command parameter OR from parent context."""
    if debug is not None:
        return debug

    ctx = click.get_current_context(silent=True)
    while ctx:
        if ctx.obj and ctx.obj.get('debug') is True:
            return True
        ctx = ctx.parent
    return False


# ==============================================================================
# CLI Group
# ==============================================================================

@click.group()
@click.version_option(version="0.0.1", prog_name="dbevo")
@click.option("--debug", is_flag=True, help="Enable debug output")
@click.pass_context
def app(ctx, debug: bool):
    """
    dbevo - Database schema migrations for Python.

    Inspired by Play Framework Evolutions.

    Configuration is loaded from:
        1. .dbevo.toml in project root (auto-detected)
        2. OS environment variables (DBEVO_*)
        3. Default values

    Required: [dbevo.database] database_uri in .dbevo.toml
    """
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug

    # Auto-detect and ensure config on every command
    ensure_config()


# ==============================================================================
# Command: status
# ==============================================================================

@app.command()
@debug_option()
@click.pass_context
def status(ctx, debug: bool):
    """Show current migration status."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo status[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_uri}[/cyan]")
    console.print(f"Migrations path: [cyan]{settings.migrations_path}[/cyan]\n")

    async def _run():
        parser = MigrationParser()
        executor = MigrationExecutor(settings, debug=debug_flag)

        try:
            await executor.connect()

            applied = await executor.get_applied_migrations()
            applied_map = {m['migration_number']: m for m in applied}

            migrations = _scan_migrations(settings.migrations_path, parser)

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Migration", style="cyan", width=40)
            table.add_column("Group", style="blue", width=15)
            table.add_column("Status", style="green", width=10)
            table.add_column("Applied At", style="yellow", width=20)

            pending_count = 0
            applied_count = 0
            reverted_count = 0

            for mig in sorted(migrations, key=lambda x: x['number']):
                key = mig['number']

                if key in applied_map:
                    db_mig = applied_map[key]
                    db_status = db_mig['status']

                    if db_status == 'reverted':
                        status = "[yellow]reverted[/yellow]"
                        reverted_count += 1
                    elif db_mig['migration_hash'] != mig['hash']:
                        status = "[red]modified[/red] ⚠️"
                    else:
                        status = "[green]applied[/green]"
                        applied_count += 1

                    applied_at = db_mig['applied_at'].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    status = "[yellow]pending[/yellow]"
                    applied_at = "-"
                    pending_count += 1

                table.add_row(
                    f"{mig['number']:06d}__{mig['description']}",
                    mig['group'],
                    status,
                    applied_at,
                )

            console.print(table)

            total_parts = []
            if pending_count:
                total_parts.append(f"{pending_count} pending")
            if applied_count:
                total_parts.append(f"{applied_count} applied")
            if reverted_count:
                total_parts.append(f"{reverted_count} reverted")

            total_str = ", ".join(total_parts) if total_parts else "0 migrations"
            console.print(f"\n[bold]Total:[/bold] {total_str}")

        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: apply
# ==============================================================================

@app.command()
@debug_option()
@click.option("--auto-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
@click.pass_context
def apply(ctx, debug: bool, auto_confirm: bool, dry_run: bool):
    """Apply pending migrations."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo apply[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_uri}[/cyan]")
    console.print(f"Migrations path: [cyan]{settings.migrations_path}[/cyan]\n")

    if dry_run:
        console.print("[yellow]Dry-run mode: no changes will be applied[/yellow]\n")

    async def _run():
        parser = MigrationParser()
        executor = MigrationExecutor(settings, debug=debug_flag)

        try:
            await executor.connect()

            applied = await executor.get_applied_migrations()
            applied_set = {m['migration_number'] for m in applied if m['status'] == 'applied'}

            migrations = _scan_migrations(settings.migrations_path, parser)
            pending = [m for m in migrations if m['number'] not in applied_set]

            if not pending:
                console.print("[green]✓[/green] No pending migrations!")
                return

            console.print(f"[bold]Will apply {len(pending)} migration(s):[/bold]")
            for m in sorted(pending, key=lambda x: x['number']):
                console.print(f"  • {m['number']:06d}__{m['description']} ({m['group']})")
            console.print()

            if not auto_confirm and not dry_run:
                if not click.confirm("Proceed?", abort=True):
                    console.print("[yellow]Aborted[/yellow]")
                    return

            for m in sorted(pending, key=lambda x: x['number']):
                console.print(f"\n[bold]Applying:[/bold] {m['number']:06d}__{m['description']}")

                if dry_run:
                    parsed = parser.parse(m['file'])
                    if parsed.ups:
                        console.print(f"[dim]```sql\n{parsed.ups.sql}\n```[/dim]")
                    continue

                result = await executor.apply_migration(m['file'])
                console.print(f"[green]✓[/green] Applied in {result['execution_time_ms']}ms")

            console.print("\n[green]✓[/green] All migrations applied successfully!")

        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: revert
# ==============================================================================

@app.command()
@debug_option()
@click.option("--to", "target", type=int, required=True,
              help="Revert to specific migration number")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
@click.option("--auto-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--force", is_flag=True, help="Proceed even if migration file modified")
@click.pass_context
def revert(ctx, debug: bool, target: int, dry_run: bool, auto_confirm: bool, force: bool):
    """Revert migrations to a specific version."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo revert[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_uri}[/cyan]")
    console.print(f"Target: [cyan]{target:06d}[/cyan]\n")

    if dry_run:
        console.print("[yellow]Dry-run mode: no changes will be applied[/yellow]\n")

    async def _run():
        executor = MigrationExecutor(settings, debug=debug_flag)
        parser = MigrationParser()

        try:
            await executor.connect()

            to_revert = await executor.revert_to(target)

            if not to_revert:
                console.print("[green]✓[/green] No migrations to revert!")
                console.print(f"[dim]Already at or before {target:06d}[/dim]")
                return

            mismatches = [m for m in to_revert if m['hash_mismatch']]

            if mismatches:
                console.print("[bold red]⚠️  WARNING: Modified migrations detected![/bold red]\n")
                for m in mismatches:
                    console.print(f"  • {m['migration_number']:06d}__{m['description']} ([yellow]{m['group']}[/yellow])")
                console.print()

                if not force:
                    console.print("[yellow]Use --force to proceed anyway (not recommended)[/yellow]")
                    raise click.Abort()

            console.print(f"[bold]Will revert {len(to_revert)} migration(s):[/bold]")
            for m in to_revert:
                console.print(f"  • {m['migration_number']:06d}__{m['description']} ([yellow]{m['group']}[/yellow])")
            console.print()

            if not auto_confirm and not dry_run:
                if not click.confirm("[red]Proceed with revert?[/red]", abort=True):
                    console.print("[yellow]Aborted[/yellow]")
                    return

            if dry_run:
                for m in to_revert:
                    migration_file = executor._find_migration_file(m['group'], m['migration_number'])
                    if migration_file:
                        parsed = parser.parse(migration_file)
                        console.print(f"\n[bold]Would revert:[/bold] {m['migration_number']:06d}__{m['description']}")
                        if parsed.downs:
                            console.print(f"[dim]```sql\n{parsed.downs.sql}\n```[/dim]")
                console.print(f"\n[yellow]✓[/yellow] Dry-run complete. {len(to_revert)} migration(s) would be reverted.")
            else:
                for m in to_revert:
                    status = "[yellow]⚠️  hash mismatch[/yellow]" if m['hash_mismatch'] else "[green]✓[/green]"
                    console.print(
                        f"{status} Reverted {m['migration_number']:06d}__{m['description']} in {m['execution_time_ms']}ms"
                    )
                console.print("\n[green]✓[/green] All migrations reverted successfully!")

        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: new
# ==============================================================================

@app.command()
@click.argument("description")
@click.option("--schema", "schema_name", default="default", help="Schema folder name")
def new(description: str, schema_name: str):
    """Create a new migration file."""
    settings = get_settings()

    console.print("[bold blue]dbevo new[/bold blue]\n")
    console.print(f"Description: [cyan]{description}[/cyan]")
    console.print(f"Schema: [cyan]{schema_name}[/cyan]")
    console.print(f"Template: [cyan]{settings.migration_template}[/cyan]\n")

    try:
        generator = MigrationGenerator(settings)
        file_path = generator.generate(description=description, schema=schema_name)
        console.print(f"[green]✓[/green] Created: [cyan]{file_path}[/cyan]")

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()


# ==============================================================================
# Command: generate
# ==============================================================================
@app.command()
@click.option(
    "--schema", "-s",
    required=True,
    help="Database schema name (e.g., core, utils)"
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for generated models"
)
@click.option(
    "--type", "-t",
    type=click.Choice(["sqlalchemy", "pydantic"]),
    default="sqlalchemy",
    help="Model type to generate (sqlalchemy or pydantic)"
)
@click.option(
    "--tables",
    help="Comma-separated table names to generate (default: all)"
)
@click.option(
    "--exclude", "-e",
    help="Override exclude columns (comma-separated)"
)
@click.option(
    "--exclude-technical",
    is_flag=True,
    help="Exclude technical columns (id, create_at, update_at)"
)
@click.option(
    "--exclude-sensitive",
    is_flag=True,
    help="Exclude sensitive columns (*_passwd, *_hash, *_token)"
)
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Show what would be generated without writing files"
)
@debug_option()
@click.pass_context
def generate(
    ctx,
    schema: str,
    output: Path,
    type: str,
    tables: str | None,
    exclude: str | None,
    exclude_technical: bool,
    exclude_sensitive: bool,
    dry_run: bool,
    debug: bool,
):
    """Generate models from database schema."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    # 🔹 Маппинг типа на шаблон
    template_map = {
        "sqlalchemy": "sqlalchemy.py.j2",
        "pydantic": "pydantic.py.j2",
    }
    template_name = template_map[type]

    # Resolve output path (relative to cwd)
    output_path = output if output.is_absolute() else (Path.cwd() / output).resolve()

    # Resolve template path
    template_path = settings.sqlalchemy_template if type == "sqlalchemy" else settings.pydantic_template
    template_dir = template_path.parent if template_path.is_file() else Path("templates")

    console.print("[bold blue]dbevo generate[/bold blue]\n")
    console.print(f"🗄️  Database: [cyan]{settings.database_uri}[/cyan]")
    console.print(f"📁 Schema: [cyan]{schema}[/cyan]")
    console.print(f"🔧 Output: [cyan]{output_path}[/cyan]")
    console.print(f"📄 Type: [cyan]{type}[/cyan] ({template_name})\n")

    # Build exclude list
    exclude_cols = settings.get_exclude_for_schema(schema)
    if exclude:
        exclude_cols = [c.strip() for c in exclude.split(',')]

    if exclude_technical:
        exclude_cols.extend(["id", "create_at", "update_at"])
    if exclude_sensitive:
        exclude_cols.extend(["*_passwd", "*_hash", "*_token", "*_secret"])

    if exclude_cols:
        console.print(f"🚫 Exclude: [yellow]{', '.join(set(exclude_cols))}[/yellow]\n")

    if dry_run:
        console.print("[yellow]Dry-run mode: no files will be written[/yellow]\n")

    async def _run():
        try:
            from ..core.model_generator import ModelGenerator

            generator = ModelGenerator(
                database_uri=settings.database_uri,
                template_dir=template_dir,
                output_dir=output_path,
                exclude_columns=exclude_cols if exclude_cols else None,
                exclude_technical=exclude_technical,
                exclude_sensitive=exclude_sensitive,
            )

            table_list = [t.strip() for t in tables.split(',')] if tables else None

            if dry_run:
                await generator.introspector.connect()
                db_tables = await generator.introspector.get_tables(schema)
                if table_list:
                    db_tables = [t for t in db_tables if t['name'] in table_list]
                await generator.introspector.close()

                console.print(f"📋 Would generate {len(db_tables)} model(s):")
                for t in db_tables:
                    cols = [c['name'] for c in t['columns'] if not generator._should_exclude(c['name'])]
                    class_name = generator._to_class_name(t['name'])
                    rel_path = generator._relative_path(output_path / f"{class_name}.py")
                    console.print(f"  • {t['name']} → {rel_path} ({len(cols)} columns)")
                console.print("\n[green]✓[/green] Dry-run complete.")
                return

            generated = await generator.generate(
                schema=schema,
                template_name=template_name,
                tables=table_list,
            )

            for f in generated:
                rel_path = generator._relative_path(f)
                console.print(f"✅ Generated: [cyan]{rel_path}[/cyan]")

            console.print(f"\n[green]✓[/green] Generated {len(generated)} {type} model(s)")

        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        except FileNotFoundError as e:
            console.print(f"[red]Template not found:[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            if debug_flag:
                import traceback
                traceback.print_exc()
            raise click.Abort()

    asyncio.run(_run())


# ==============================================================================
# Command: init
# ==============================================================================

@app.command()
@debug_option()
@click.pass_context
def init(ctx, debug: bool):
    """Initialize dbevo tracking schema and tables."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo init[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_uri}[/cyan]\n")

    async def _run():
        executor = MigrationExecutor(settings, debug=debug_flag)
        try:
            await executor.connect()
            await executor.init_schema()
            console.print("[green]✓[/green] dbevo schema initialized successfully!")
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Helper Functions
# ==============================================================================

def _scan_migrations(migrations_path: Path, parser: MigrationParser) -> list[dict]:
    """Scan migrations directory and parse all .sql files."""
    migrations = []

    if not migrations_path.exists():
        return migrations

    for sql_file in migrations_path.rglob("*.sql"):
        if sql_file.name.endswith('.j2'):
            continue

        try:
            parsed = parser.parse(sql_file)
            migrations.append({
                'file': sql_file,
                'group': parsed.migration_group,
                'number': parsed.migration_number,
                'description': parsed.description,
                'hash': parsed.ups_hash,
            })
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to parse {sql_file}: {e}")

    return migrations


# ==============================================================================
# Entry Point
# ==============================================================================

if __name__ == "__main__":
    app()
