import os
import sys
from alembic.config import Config
from alembic import command

config = Config()
config.set_main_option("script_location", f"services/{sys.argv[1]}/migrations")
config.set_main_option(
    "sqlalchemy.url",
    os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1),
)
command.upgrade(config, "head")
print(f"Alembic {sys.argv[1]}: schema upgraded to head", flush=True)
