FROM python:3.12-slim
WORKDIR /project/backend
COPY backend/pyproject.toml .
COPY backend/app ./app
RUN pip install --no-cache-dir '.[test]'
COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/tests ./tests
COPY data /project/data
