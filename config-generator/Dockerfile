FROM python:3.13-alpine

# Unprivilegierter User. /output gehört ihm, damit ein frisch angelegtes
# Named Volume (prometheus_targets) beim ersten Mount diese Ownership übernimmt.
RUN adduser -D -H -u 10001 generator \
 && mkdir /output \
 && chown generator:generator /output

WORKDIR /app
COPY generate_targets.py .

USER 10001:10001

ENTRYPOINT ["python", "generate_targets.py"]
