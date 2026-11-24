# The unit tests, run in a clean container:
#   docker compose --profile test run --rm unit-tests
#
# Build context: this tests folder. docker-compose.yml also passes the services folder as a
# second, named build context ("services"), so the tests can import every service's code.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /suite

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin tester

COPY requirements.txt tests/requirements.txt
RUN pip install -r tests/requirements.txt

# hadolint ignore=DL3022
COPY --from=services . services/
COPY . tests/

USER 10001

# -p no:cacheprovider: pytest doesn't try to write a cache folder into the image
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit"]
