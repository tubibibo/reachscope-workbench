FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE THIRD_PARTY.md ./
COPY src ./src
COPY frontend/contracts ./frontend/contracts
RUN pip install --no-cache-dir .
EXPOSE 8765
VOLUME ["/app/.workbench"]
CMD ["reachscope-workbench", "serve", "--port", "8765", "--data", "/app/.workbench"]
