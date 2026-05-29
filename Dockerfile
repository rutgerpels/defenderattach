FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV DASH_HOST=0.0.0.0
ENV DASH_PORT=8050
ENV DASH_DEBUG=false

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY src ./src
COPY assets ./assets
COPY docs ./docs

RUN mkdir -p inputfolder inputfolder_opty output

EXPOSE 8050

CMD ["python", "app.py"]
