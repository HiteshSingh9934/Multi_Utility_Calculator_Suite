# Secrets

`db_password.txt` holds the PostgreSQL password. Docker Compose gives it to the `db`,
`history-service` and `db-backup` containers as a Docker secret: a read-only file at
`/run/secrets/db_password`, so the password never appears in `docker inspect` or in an
environment variable.

It must match the password the database volume was created with (`calc_password` by default).
Keep the password on one line, with nothing after it.
To change the password for a new database, edit the file and reset the volume with
`docker compose down -v` (this deletes saved history).
