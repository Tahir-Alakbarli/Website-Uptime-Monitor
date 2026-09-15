FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY website_monitoring_app.py .
COPY templates/ templates/

EXPOSE 8000

CMD ["python", "-u", "website_monitoring_app.py"]