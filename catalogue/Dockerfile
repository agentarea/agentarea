FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install poetry
RUN pip install poetry

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY .env ./
COPY README.md ./
COPY src ./src
# Configure poetry to not create virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install

# Expose port
EXPOSE 8000

# Add wait-for-it script
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

# Create entrypoint script
# RUN echo '#!/bin/bash\n\
#     /wait-for-it.sh db:5432 -- poetry run alembic upgrade head\n\
#     poetry run uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --reload\n'\
#     > /entrypoint.sh && chmod +x /entrypoint.sh

RUN echo '#!/bin/bash\n\
    poetry run uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --reload\n'\
    > /entrypoint.sh && chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]