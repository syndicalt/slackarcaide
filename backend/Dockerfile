FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" "pydantic-settings>=2.3" "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" "redis>=5.0" "websockets>=12.0" "python-chess>=1.999" "mcp>=2.0"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
