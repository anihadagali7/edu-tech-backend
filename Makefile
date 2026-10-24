.PHONY: install fmt lint typecheck test run alembic-init alembic-up alembic-down pre-commit

PY = python
UV = uvicorn
PKG = adaptive-quiz-backend

install:
\t$(PY) -m pip install -U pip
\t$(PY) -m pip install -e ".[dev]"
\tpre-commit install

fmt:
\tblack .
\truff format .

lint:
\truff .

typecheck:
\tmypy .

test:
\tpytest -q

run:
\t$(PY) -m app.main

# Alembic shortcuts (config lives under app/db/migrations/)
alembic-init:
\t@echo "Alembic already scaffolded under app/db/migrations/"

alembic-up:
\talembic -c app/db/migrations/alembic.ini upgrade head

alembic-down:
\talembic -c app/db/migrations/alembic.ini downgrade -1

pre-commit:
\tpre-commit run --all-files