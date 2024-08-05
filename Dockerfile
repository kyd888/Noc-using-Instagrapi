FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install --upgrade pip
RUN pip install --use-deprecated=legacy-resolver -r requirements.txt

COPY . .

CMD ["python", "app.py"]
