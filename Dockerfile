FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r ./requirements.txt

WORKDIR /card
COPY . /card

RUN chgrp -R 0 /card && chmod -R g=u /card
RUN chmod -R g+rwx /card

EXPOSE 8080
ENV PORT=8080

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]