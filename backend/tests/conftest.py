"""Suite-wide deterministic infrastructure defaults, applied before collection."""

import os

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
