FROM python:3.11-slim as builder

WORKDIR /app

# Install poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-interaction --no-ansi --no-root


FROM python:3.11-slim as runner

WORKDIR /app

# Copy only necessary files from builder
COPY --from=builder ./app ./app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Set environment variables
ENV PYTHONPATH=/app
ENV PORT=${PORT:-8000}

# Expose the port
EXPOSE ${PORT}

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "${PORT}"]