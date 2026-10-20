FROM python:3.14.8-slim-trixie

WORKDIR /app

RUN pip install --no-cache-dir uv==0.13.3

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

COPY server.py .

EXPOSE 8123

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8123"]
