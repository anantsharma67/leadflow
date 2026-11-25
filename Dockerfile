FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY leadflow leadflow
COPY data data
ENV LEADFLOW_PROVIDER=mock
EXPOSE 8000
CMD ["uvicorn", "leadflow.api:app", "--host", "0.0.0.0", "--port", "8000"]
