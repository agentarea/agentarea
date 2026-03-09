FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

COPY server.py .

EXPOSE 8123

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8123"]
