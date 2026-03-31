# dbevo Example Project

Quick start example for dbevo.

## Setup

```bash
# 1. Copy example to your project
cp -r examples/* /path/to/your/project/

# 2. Configure database
# Edit .dbevo.toml with your database credentials
vim .dbevo.toml

# 3. Initialize dbevo schema
poetry run dbevo init

# 4. Create your first migration
poetry run dbevo new "create_users_table" --schema core

# 5. Apply migration
poetry run dbevo apply

# 6. Generate models
poetry run dbevo generate --schema core --output api/modules/core/models --type sqlalchemy
poetry run dbevo generate --schema core --output api/modules/core/schemas --type pydantic
```
