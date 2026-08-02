FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

RUN useradd --create-home --uid 1000 dashboard
WORKDIR /app

COPY dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY dashboard/app.py /app/app.py
COPY dashboard/loaders.py /app/loaders.py
COPY dashboard/views/ /app/views/
COPY .streamlit/ /app/.streamlit/

USER dashboard

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
