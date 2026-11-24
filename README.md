# Multi-Utility Calculator Suite using Docker and Microservices

Fifteen calculators in one web app: everyday and scientific calculators, a function plotter, an
interactive **3D graph visualizer**, 3D shapes and vectors, **matrices with exact fractions**,
calculus and statistics, plus the GST, EMI and student tools. It is built as **eight Python
microservices** behind an **Nginx API gateway**, saves every result in **PostgreSQL** on a Docker
volume, caches graphs in **Redis**, is monitored with **Prometheus and Grafana**, runs with
**Docker Compose** or on **Kubernetes**, is tested by a **CI pipeline** and shipped by a **CD pipeline**
(Trivy scan, GitHub Container Registry, Argo CD). The page opens on a **live map of the containers**
that shows which ones are running, and has a **dark and a light theme**.

**New in version 3.2.1 (interface update):** every worked solution is now **played step by step**: the steps
open one under the other, the line of working is written from left to right, the result of each line lights
up, and a rail joins the numbered markers until the answer closes the solution. The controls above it are
Pause/Play, Next step, Replay, Show all, and a speed button (1x, 2x, 3x). With *reduce motion* switched on in
the system, or when printing, every step is shown at once. The rest of the interface got a refresh too: a soft
light behind the page, a glow that follows the pointer, a headline that arrives word by word, an icon beside
each tool's heading, a light sheen on the main buttons, and a loading outline while an answer is on its way.
The animation is plain CSS and JavaScript (`steps.js`, `fx.js`); nothing was added to the images' dependencies.

**Overview page redesign (version 3.3, same image tags):** the first page now opens on an **aurora background**
behind the headline (a WebGL shader; it follows the dark/light theme and falls back to a plain page if WebGL is
not available), with a **worked solution playing by itself** beside the Ask box. The Ask field has an animated
border while you type, its label has a slow shimmer, and the main buttons throw a few sparks when pressed.
These effects are ports of components from [React Bits](https://github.com/DavidHDev/react-bits)
(Aurora, StarBorder, ShinyText, ClickSpark), rewritten in plain JavaScript and CSS (`aurora.js`, `fx.js`).
React Bits is MIT licensed with the Commons Clause, which allows use in a project like this one but not
selling the components themselves. Everything is switched off by *reduce motion* and is hidden when printing.

**New in version 3.2:** **worked solutions** (every derivative, integral, equation, matrix and EMI/GST
answer can show its steps), an **Ask box** that understands plain sentences such as *EMI for 5 lakh at 9%
for 3 years*, a **chaos lab** that breaks a container on purpose so you can watch it recover, and a
**CD pipeline**.

| Tool | What it does | Microservice |
|---|---|---|
| Overview (start page) | A live map: your browser, the Nginx gateway, the eight containers, Redis and PostgreSQL. Each tool sits beside the container that answers it, and a stopped container turns red | gateway (checks every service's `/health` every 10 seconds) |
| Calculator | Add, subtract, multiply, divide, power, remainder, percentage of | `calc-service` |
| Scientific calculator | Any expression: `sin(30) + 2^10 + √16`, `5!`, `10 nCr 3`, `ln`, `log`, degrees or radians, `Ans` | `math-service` |
| Unit converter | Length, weight, temperature, area, volume, speed, time, data, energy, pressure | `converter-service` |
| Function plotter | Up to four functions of x on one graph, with roots, maxima, minima and y-intercepts marked | `math-service` |
| 3D graph | Surfaces z = f(x, y), 3D curves (helix, trefoil knot) and parametric surfaces (torus, Möbius strip); rotate, zoom, auto-spin, contour lines | `math-service` |
| 3D shapes | Volume and surface areas of 9 solids (cube to torus) with a 3D model you can turn around | `math-service` |
| 3D vectors | Dot and cross product, lengths, angle, projection, triple product, drawn as arrows in 3D | `matrix-service` |
| Matrices | Determinant, inverse, transpose, rank, trace, power, row reduction (RREF), A ± B, A × B, kA, solving AX = B, eigenvalues and eigenvectors; exact fractions, so 1/3 stays 1/3 | `matrix-service` |
| Calculus | Exact derivative (f′ and f″), slope and tangent at a point, definite integral and area, roots and turning points, all on one graph | `math-service` |
| Statistics | Mean, median, mode, quartiles, standard deviation, outliers, skewness; histogram, box plot, line of best fit with r and r² | `math-service` |
| GST calculator | Add GST to a price or take it out; CGST + SGST within a state, IGST between states | `finance-service` |
| EMI calculator | Monthly EMI, total interest, year-by-year schedule | `finance-service` |
| CGPA and percentage | Both directions; MIT ADT University (× 9.56), CBSE (× 9.5), × 10, (CGPA − 0.75) × 10, or your own formula | `student-service` |
| Marks and grades | Percentage, average, grade per subject (10-point scale), SGPA when credits are given | `student-service` |
| Attendance | Current %, classes you can miss, or classes you must attend to reach the target | `student-service` |
| Ask box (on the start page, and in the search on Ctrl+K) | Type a sentence: `derivative of x^2 sin(x)`, `solve x^2 - 5x + 6 = 0`, `inverse of [[2,1],[5,3]]`, `EMI for 5 lakh at 9% for 3 years`, `18% GST on 2499`, `plot sin(x)`, `10 km in miles`. It shows the answer **with the steps**, says which services worked it out, and opens the real tool on request. No AI model is involved: a rule-based reader turns the sentence into a request to the other services | `solver-service` (calls `finance-service`, `converter-service`, `calc-service` and `math-service`) |
| Show steps (Calculus, Matrices, GST, EMI) | A worked solution beside the normal answer: product, quotient and chain rules named one by one; integration by parts; Gauss-Jordan row operations; the EMI formula with your numbers. Every answer is checked a second way before it is shown (a derivative against the numeric slope, an integral by differentiating it back) | `solver-service` |
| Chaos lab | Pick a container and crash it, slow it down or make it return errors. A board shows each container's uptime, and an event log shows it stopping and Docker or Kubernetes starting it again | every service's `/chaos` route (only when `CHAOS_ENABLED=true`) |
| History | Every result is saved; click one to load it back (graphs are redrawn straight from Redis) | `history-service` + PostgreSQL |

---

## Architecture

```
                         Browser: http://localhost:8080
                                       |
                 +---------------------v----------------------+
                 |              gateway  (Nginx)              |  serves the web page and routes
                 | /api/calc /api/math /api/matrix /api/solver |  /api/<name>/... to <name>-service
                 +--+-------+--------+--------+-------+-------+
                    |       |        |        |       |
           +--------v-+ +---v----+ +-v------+ v-----+ v---------+ +-----------+
           |  calc-   | |convert-| |finance-| |stud- | |  math-   | |  matrix-  |   network "app"
           | service  | |  er    | |service | | ent  | | service  | |  service  |
           +----+-----+ +---+----+ +---+----+ +--+---+ +----+-----+ +-----+-----+
                |   each result: POST /records   |          |             |
                +---------------+----------------+----------)-------------+
                                |                           |  graphs
                       +--------v--------+         - - - - -|- - - - - -   network "cache"
                       | history-service |                  v              (internal)
                       +--------+--------+         +-----------------+
          - - - - - - - - - - - | - - - - - - -    |  cache (Redis)  |-- volume cache-data
                       +--------v--------+         +-----------------+
                       | db (PostgreSQL) |      network "data" (internal: only history-service)
                       +--------+--------+
                                |
                     volume: calculator-app_db-data   (data survives restarts)

   Optional, "monitoring" profile:  Prometheus scrapes every service's /metrics  ->  Grafana dashboard
```

* The browser only talks to the gateway, so the services are never exposed and no CORS setup is needed.
* Each microservice has its own image and can be stopped, restarted or scaled on its own. If
  `history-service` or the database is down, calculations still work; they just aren't saved.
  If Redis is down, graphs are still drawn; they're just worked out every time.
* `solver-service` calls the other services over the same `app` network (for example `finance-service`
  for the EMI figures), so the Ask box is itself a small example of services working together. If one of
  them is down it still answers with the worked solution and says what it could not do.
* The two maths services never run code typed by the user: expressions are read by a small
  parser written for this project (no `eval`), and matrices are worked out with exact fractions.
* Nginx looks service names up again every 10 seconds, so restarted or scaled containers are
  picked up without restarting the gateway.

## Project structure

```
calculator-app/
├── docker-compose.yml             all containers, networks, volumes, secret, health checks, profiles, watch
├── .env                           ports, database name and user
├── secrets/db_password.txt        the database password (a Docker secret)
├── gateway/
│   ├── Dockerfile                 nginx:1.30-alpine + the web page (Plotly is pre-compressed at build time)
│   ├── default.conf.template      Nginx config: web server + API gateway (filled in at startup)
│   └── html/                      index.html, styles.css, app.js (the tools), math.js (graphs),
│                                  ui.js (map, themes, search, copy), solver.js (Ask box, steps, chaos lab),
│                                  steps.js (plays a worked solution), fx.js (headline, icons, glow, sparks),
│                                  aurora.js (the overview background, from React Bits),
│                                  fonts/ (IBM Plex), vendor/plotly.min.js
├── services/
│   ├── calc-service/              app.py, requirements.txt, Dockerfile, .dockerignore
│   ├── converter-service/         "
│   ├── finance-service/           "
│   ├── student-service/           "
│   ├── math-service/              " + expr.py (expression parser), analysis.py (roots, integrals,
│   │                                statistics), solids.py (3D shapes)
│   ├── matrix-service/            "
│   ├── solver-service/            " + expr.py (the same parser as math-service), calculus_steps.py, algebra_steps.py,
│   │                                finance_steps.py (the step engines), asking.py (reads sentences)
│   └── history-service/           " + schema.sql (the PostgreSQL table)
├── monitoring/
│   ├── prometheus.yml             which services Prometheus collects numbers from
│   └── grafana/                   data source, dashboard loader and the dashboard itself
├── k8s/                           Kubernetes manifests (apply in file-name order)
│   ├── 00-namespace.yaml          namespace calc-suite
│   ├── 01-config.yaml             ConfigMap (settings) + Secret (database login)
│   ├── 02-database.yaml           PostgreSQL StatefulSet + PersistentVolumeClaim + Services
│   ├── 03-cache.yaml              Redis Deployment + Service
│   ├── 10…17-*-service.yaml       Deployment + Service for each microservice
│   ├── Kustomization              lets Kustomize and Argo CD use this folder as a base (kubectl ignores it)
│   ├── 20-gateway.yaml            gateway Deployment + NodePort Service (port 30080)
│   └── extras/                    autoscaling (HPA) and network policies (optional)
├── deploy/                        CD: the registry overlay and the Argo CD Application (see deploy/README.md)
├── tests/
│   ├── unit/                      437 unit tests of the services' code (pytest)
│   ├── smoke_test.py              end-to-end test of every tool, the solver and the chaos routes through the gateway
│   └── Dockerfile                 runs the unit tests in a container
├── .github/workflows/ci.yml       CI and CD pipeline: tests, linting, build, smoke test, Trivy scan, publish, GitOps
└── backups/                       database backups are written here
```

## Docker and Kubernetes concepts used

| Concept | Where |
|---|---|
| Dockerfile best practices | slim base images, dependencies copied before code (layer caching), non-root user, `HEALTHCHECK`, `.dockerignore`, gunicorn instead of the Flask dev server, files pre-compressed at build time |
| Multi-container app | `docker-compose.yml`: 11 containers started with one command (up to 17 with the profiles) |
| Independent deployment and image tags | the services are `3.0` and the gateway `3.1`: the new web page only needed the gateway image rebuilt and its container replaced, while the other containers kept running |
| API gateway / reverse proxy | `gateway/default.conf.template` |
| Custom networks and isolation | `app`, plus two `internal` networks: `data` (only history-service reaches PostgreSQL) and `cache` (only math-service reaches Redis) |
| Service discovery | containers find each other by name (`history-service`, `db`, `cache`) through Docker's DNS |
| Named volumes | `db-data` (PostgreSQL), `cache-data` (Redis snapshot), `prometheus-data`, `grafana-data` |
| Bind mounts | `./backups`, `./tests`, `./monitoring` (configuration files read by Prometheus and Grafana) |
| Docker secrets | the database password is a file mounted at `/run/secrets/db_password`, not an environment variable |
| Caching | Redis keeps finished graphs for an hour (cache-aside, least-recently-used eviction) |
| Health checks and start order | every service has one; `history-service` waits for `db` and `math-service` for `cache` to be *healthy* |
| Restart policy and resource limits | `restart: unless-stopped`; CPU and memory limits per container |
| Configuration | environment variables, `.env`, YAML anchors for shared settings |
| Profiles | `monitoring` (Prometheus, Grafana), `tools` (Adminer), `backup` (db-backup), `test` (unit-tests, smoke-test) |
| Live development | `docker compose watch`: edit the web page and refresh; edit a service and it is rebuilt |
| Monitoring | every service exposes Prometheus metrics; Grafana dashboard provisioned from files |
| Scaling and load balancing | `docker compose up -d --scale math-service=3` |
| Testing and CI | unit tests, end-to-end smoke test, GitHub Actions pipeline |
| Chaos engineering | `CHAOS_ENABLED`, the `/chaos` route and the chaos lab: restart policies and Kubernetes self-healing shown by breaking things on purpose |
| Continuous delivery and GitOps | Trivy scan, images published to GitHub Container Registry with an SBOM, Kustomize overlay, Argo CD Application |
| Kubernetes | Namespace, ConfigMap, Secret, Deployment, Service (ClusterIP and NodePort), StatefulSet with a PersistentVolumeClaim, readiness and liveness probes, rolling updates, scaling, self-healing, HorizontalPodAutoscaler, NetworkPolicy |

---

## 1. Upgrade (keeps your saved history)

**From version 3.1.** One new service and a new page, so rebuild everything that changed. In Command Prompt:

```
cd /d D:\calculator-app
docker compose up -d --build --remove-orphans
```

This builds `solver-service`, rebuilds the other seven services (they gained the chaos route) and the
gateway, and recreates the containers. The database volume is kept. Open **http://localhost:8080**,
press **Ctrl+F5** once, and look for the Ask box on the start page. The top right should say
**All 8 services running**. Also copy the new `.env` (it contains `CHAOS_ENABLED=true`), or add that line yourself.

**From version 3.** Only the web page changed, so only the gateway is rebuilt. In Command Prompt:

```
cd /d D:\calculator-app
docker compose up -d --build gateway
```

This builds `calculator-app/gateway:3.1` and replaces the gateway container; the services,
the database and the cache keep running. Open **http://localhost:8080** and press **Ctrl+F5** once.
You should see the map of the containers.

**From version 2.** Copy this project's files over `D:\calculator-app` (replace the old files).
Then, in Command Prompt:

```
cd /d D:\calculator-app
docker compose up -d --build --remove-orphans
```

This builds the two new services and the updated ones, downloads Redis, and recreates the
containers. The database volume is kept, so your history is still there; the password now comes
from `secrets\db_password.txt`, which contains the same `calc_password` as before. Open
**http://localhost:8080** and press **Ctrl+F5** once, so the browser loads the new page. The top
right should say **All 8 services running**.

## 2. Run with Docker Compose

```
cd /d D:\calculator-app
docker compose up -d --build
docker compose ps
```

The first build downloads the base images and takes a few minutes. Wait until `docker compose ps`
shows the services as `healthy`, then open **http://localhost:8080**.

Test every tool in one go (runs inside a container, so you don't need Python on Windows):

```
docker compose run --rm smoke-test
```

Every line should say `PASS`. Run the 256 unit tests too:

```
docker compose run --rm unit-tests
```

Stop and start later:

```
docker compose stop          (pause everything; docker compose start brings it back)
docker compose down          (remove the containers; the volumes stay)
docker compose up -d         (start again; no --build needed unless you changed code)
```

## 3. Things to demonstrate

**The web page**

* The start page is a map of the system: your browser, the Nginx gateway, the eight containers,
  with Redis under math-service and PostgreSQL under history-service. Every tool sits beside the
  container that answers it; click one to open it. The map is live and checks every service
  every 10 seconds (see *Failure handling* below).
* The sun and moon button switches between the dark and the light theme. Use light on a
  projector. The graphs redraw in the new colours, and the browser remembers the choice.
* Press **Ctrl K** (or **/**) and type, for example, `loan` or `3d` to jump to a tool.
* Every answer has a **Copy** button, and each tool says which container runs it
  (*Runs on math-service*).

**The maths tools**

* *3D graph*: pick a preset (Sombrero, Peaks, Torus, Trefoil knot…), drag to rotate, scroll to
  zoom, press **Rotate** to make it spin. Type your own: `sin(x)cos(y)` or `x^2 - y^2`.
* *Function plotter*: plot `sin(x)`, `x^3 - 3x` and `e^x` together; roots and turning points are marked.
* *Matrices*: inverse of the example matrix gives exact fractions (`3/4`, `1/2`…); try
  *Eigenvalues*, or *Solve AX = B* for simultaneous equations.
* *Calculus*: `x^3 - 3x` gives f′(x) = 3x² − 3, the tangent at x = 2 and the area between −2 and 2.

**Worked solutions and the Ask box**

* On the start page type `derivative of x^2 sin(x)` in the Ask box and press **Show me**. The answer comes
  with numbered steps (the product rule, then each part differentiated), a line saying which services
  worked it out, and an **Open in Calculus** button. Try `integrate x e^x from 0 to 2`,
  `solve x^2 - 5x + 6 = 0`, `inverse of [[2,1],[5,3]]`, `EMI for 5 lakh at 9% for 3 years`, `18% GST on 2499`,
  `plot sin(x)`, `10 km in miles`. Things it cannot read get a clear message with examples.
* In *Calculus*, *Matrices*, *GST* and *EMI* press **Show steps** beside the normal button.
* Stop one service (`docker compose stop finance-service`) and ask for an EMI again: the Ask box still gives the worked
  solution and says that finance-service was not answering. Start it again with `docker compose start finance-service`.
* Nothing is sent to an AI model. The sentence is read by rules in `services/solver-service/asking.py`, the
  steps are written by hand-coded engines and checked a second way, and nothing the user types is ever run as code.

**The chaos lab (break it on purpose)**

Open **Chaos lab** in the menu. Pick `calc-service`, choose **Crash** and press **Break it**. The board turns the
tile red ("not answering"), the log says when it stopped, and a second or two later it says the container is back
and that its uptime started again from zero: Docker restarted it (`restart: unless-stopped`). Meanwhile the
other tools kept working. **Slow** makes a container take 2.5 seconds per request for 30 seconds, **Errors** makes
it return an error for 30 seconds, **Surprise me** picks one at random, and **Back to normal** clears every fault.
In another window watch Docker do it:

```
docker compose ps
docker compose events --filter event=die --filter event=start
```

How it works: every service has a `POST /chaos` route that does nothing unless the container was started with
`CHAOS_ENABLED=true` (set in `.env`; the default in the code is off). Crash sends the gunicorn master process a
SIGTERM, so the container really exits. The service's `/health`, `/ready` and `/metrics` pages are never disturbed,
and the count of injected faults is in Prometheus (`chaos_injections_total`) and on the Grafana dashboard.
Switch it off for a "real" deployment with `CHAOS_ENABLED=false`.

**The Redis cache**

Draw a 3D graph, then draw the same graph again: the line under the graph changes to
*Answered by math-service (…), from the Redis cache*. Look inside Redis:

```
docker compose exec cache redis-cli dbsize
docker compose exec cache redis-cli info stats | findstr keyspace
```

**Monitoring with Prometheus and Grafana**

```
docker compose --profile monitoring up -d
```

Open **http://localhost:3000**: the *Calculator Suite* dashboard shows requests per second,
response times, the graph cache hit rate, memory per service and which services are up (log in
as `admin` / `admin` if you want to edit it). Use the app for a minute and watch it change.
Prometheus itself is at http://localhost:9090 (try the query `http_requests_total`, or
*Status → Targets* to see all eight services). Stop a service with
`docker compose stop matrix-service` and watch *Up or down* turn red.

**Docker secrets**

```
docker compose exec history-service cat /run/secrets/db_password
docker inspect calculator-app-history-service-1 --format "{{.Config.Env}}"
```

The password is a file inside the container; it isn't in the container's environment.

**Live reload with `docker compose watch`**

```
docker compose watch
```

Leave it running and edit `gateway\html\styles.css` (or any page file): refresh the browser and
the change is there, with no rebuild. Edit a service's `app.py` and that service alone is rebuilt
and restarted. Press Ctrl+C to stop watching (the app keeps running).

**Data survives restarts (named volume)**

```
docker compose down
docker compose up -d
```

Your history is still there. See the volumes and look inside the database:

```
docker volume ls
docker volume inspect calculator-app_db-data
docker compose exec db psql -U calc_user -d calculator -c "SELECT id, tool, summary, created_at FROM history ORDER BY id DESC LIMIT 10;"
```

**Browse the database in a web page (Adminer)**

```
docker compose --profile tools up -d
```

Open http://localhost:8081 and log in with System *PostgreSQL*, Server `db`,
Username `calc_user`, Password `calc_password`, Database `calculator`.

**Back up and restore (bind mount)**

```
docker compose run --rm db-backup
```

The file appears in the `backups` folder on your computer. To restore one (Command Prompt):

```
docker compose exec -T db psql -q -o /dev/null -U calc_user -d calculator < backups\calculator-YYYYMMDD-HHMMSS.sql
```

In PowerShell, use `Get-Content backups\calculator-YYYYMMDD-HHMMSS.sql | docker compose exec -T db psql -q -o /dev/null -U calc_user -d calculator` instead.

**Scaling and load balancing**

```
docker compose up -d --scale math-service=3
docker compose ps math-service
```

Draw a few graphs. The line under each result, *Answered by math-service (container ID)*, changes
as requests are spread across the three containers (Prometheus finds all three by itself). Scale
back with `--scale math-service=1`.

**Failure handling and recovery**

```
docker compose stop converter-service
```

On the overview map its box turns red, its line to the gateway is dashed, and the note under
the map names it. The unit converter shows an error, but every other tool keeps working.
`docker compose start converter-service` and it recovers within about 10 seconds, with no page
reload. Stopping `history-service` shows *Not saved to history* under each result, and
stopping `cache` just makes graphs a little slower.

**Network isolation**

```
docker compose exec gateway ping -c 1 db
docker compose exec gateway ping -c 1 cache
docker compose exec history-service python -c "import socket; print(socket.gethostbyname('db'))"
```

The gateway can't even resolve `db` or `cache`; `history-service` can reach `db`.

**Logs and resource use**

```
docker compose logs -f gateway math-service
docker stats
```

---

## 4. Run on Kubernetes (Docker Desktop)

1. In Docker Desktop, open **Settings → Kubernetes**, turn on **Enable Kubernetes**, choose the
   **kubeadm** cluster, and apply. Wait until Kubernetes shows as running.
   (A *kind* cluster can't see images you build locally; see Troubleshooting.)
2. Point `kubectl` at it, build the images, and deploy:

```
kubectl config use-context docker-desktop
docker compose build
kubectl apply -f k8s/
kubectl get pods -n calc-suite -w
```

Press Ctrl+C once every pod is `Running` and `READY 1/1`. Then open **http://localhost:30080**.

Run the smoke test against Kubernetes:

```
docker run --rm -v "%cd%\tests:/tests" calculator-app/calc-service:3.0 python /tests/smoke_test.py http://host.docker.internal:30080
```

(If you have Python on Windows, `python tests\smoke_test.py http://localhost:30080` does the same.)

The Compose version and the Kubernetes version can run at the same time (ports 8080 and 30080);
they have separate databases. Run `docker compose down` first if your computer is short on memory.

**Kubernetes things to demonstrate**

| What | Command |
|---|---|
| See everything | `kubectl get all -n calc-suite` |
| Scale up (more pods behind one Service) | `kubectl scale deployment math-service -n calc-suite --replicas=4` then `kubectl get pods -n calc-suite -l app=math-service` |
| Self-healing (pods come back) | `kubectl delete pod -n calc-suite -l app=converter-service` then `kubectl get pods -n calc-suite` |
| Data survives a database pod restart | `kubectl delete pod db-0 -n calc-suite`, wait, then check the history in the page |
| The volume claim | `kubectl get pvc -n calc-suite` |
| Rolling update and rollback | `kubectl rollout restart deployment/gateway -n calc-suite`, `kubectl rollout status deployment/gateway -n calc-suite`, `kubectl rollout undo deployment/gateway -n calc-suite` |
| Switch versions with a rolling update | `kubectl set image deployment/gateway gateway=calculator-app/gateway:3.0 -n calc-suite` brings back the version 3 page (if that image is still on your computer), then `kubectl rollout undo deployment/gateway -n calc-suite` returns to 3.1. Refresh the browser after each |
| Config and secret | `kubectl get configmap app-config -n calc-suite -o yaml`, `kubectl get secret db-credentials -n calc-suite -o yaml` |
| Probes and events | `kubectl describe pod -n calc-suite -l app=math-service` |
| Logs | `kubectl logs -n calc-suite deployment/math-service` |
| Query the database | `kubectl exec -it db-0 -n calc-suite -- psql -U calc_user -d calculator -c "SELECT count(*) FROM history;"` |
| The Redis cache | `kubectl exec -n calc-suite deployment/cache -- redis-cli dbsize` |

**Optional: autoscaling (HPA)**

Docker Desktop doesn't include metrics-server, which the autoscaler needs. Install it, allow it
to read Docker Desktop's kubelet, then add the autoscalers (calc-service: 2 to 6 pods,
math-service: 2 to 8 pods, both at 60% CPU):

```
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type=json --patch-file k8s/extras/metrics-server-patch.json
kubectl apply -f k8s/extras/hpa.yaml
kubectl get hpa -n calc-suite -w
```

Generate load from a second Command Prompt and watch the replica count rise:

```
kubectl run load -n calc-suite --rm -it --restart=Never --image=busybox:1.36 -- sh -c "while true; do wget -q -O /dev/null --post-data '{\"expression\": \"sin(x)cos(y)\", \"resolution\": 120, \"history\": false}' --header 'Content-Type: application/json' http://math-service:5000/plot3d; done"
```

(Redis would answer repeated graphs instantly, so to keep math-service busy change the expression,
or stop the cache first with `kubectl scale deployment cache -n calc-suite --replicas=0`.)

**Optional: network policies**

`k8s/extras/network-policies.yaml` gives Kubernetes the same rules as the private Docker networks:
only history-service may connect to PostgreSQL and only math-service to Redis. Kubernetes enforces
them when the cluster's network plugin supports it (Calico or Cilium do; Docker Desktop's doesn't).

```
kubectl apply -f k8s/extras/network-policies.yaml
kubectl get networkpolicy -n calc-suite
```

**Break a pod on purpose (chaos lab on Kubernetes)**

Each service has two pods, so the lab shows two kinds of recovery. In one window run `kubectl get pods -n calc-suite -w`,
then crash `calc-service` in the Chaos lab (http://localhost:30080): one pod's `RESTARTS` column goes from 0 to 1 within
seconds, and because the other pod kept answering, users noticed nothing. `kubectl delete pod <name> -n calc-suite`
does the same by hand. The ConfigMap in `k8s/01-config.yaml` carries `CHAOS_ENABLED: "true"`.

**Deploy from the registry with Argo CD (GitOps)**

`deploy/` holds the other way to deploy: the pipeline publishes the images to GitHub Container Registry and Argo CD keeps
the cluster equal to Git. See `deploy/README.md`.

**Remove it from Kubernetes**

```
kubectl delete -f k8s/
```

This deletes the namespace, including its database volume.

---

## 5. Continuous integration (GitHub Actions)

If you put the project on GitHub, `.github/workflows/ci.yml` runs on every push:

1. **Unit tests**: the 437 pytest tests in `tests/unit`.
2. **Lint**: every Dockerfile with hadolint, the Kubernetes manifests (and the registry overlay) with kubeconform, and the
   Compose file with `docker compose config`. A **Trivy** scan of the configuration files lists risky settings (report only).
3. **Build and test**: builds every image, starts the whole app with `docker compose up --wait`,
   runs the smoke test and the unit tests inside Docker, and prints the logs if anything fails.

The results appear in the repository's **Actions** tab.

### Continuous delivery (CD)

After the three CI jobs pass, two more jobs run, but only for pushes to `main` and for tags that start with `v`
(pull requests and other branches stop after the scan):

4. **Scan and publish** (one job for each of the nine images): builds the image, scans it with **Trivy**
   (it reports HIGH and CRITICAL findings, and **stops the pipeline on a CRITICAL vulnerability that has a fix**), then
   pushes it to **GitHub Container Registry** as `ghcr.io/<you>/calculator-app/<service>:sha-<commit>` (and `latest`, or
   the version for a `v3.2.0` tag), with an SBOM and build provenance attached.
5. **GitOps**: writes the new tag into `deploy/overlays/ghcr/kustomization.yaml` and commits it. **Argo CD** watches that
   file and rolls the cluster forward; reverting the commit rolls it back. The cluster is never changed by the pipeline itself.

This is continuous *delivery*: every good commit on `main` becomes a deployed version without anyone typing a command.
Setup steps are in `deploy/README.md`.

---

## Command reference

| Command | Why |
|---|---|
| `docker compose build` | Build all the images from their Dockerfiles |
| `docker compose up -d --build` | Build if needed, then start everything in the background |
| `docker compose up -d --build math-service` | Rebuild and restart just one service after changing its code |
| `docker compose watch` | Keep containers up to date while you edit the code |
| `docker compose ps` | Containers, health status and published ports |
| `docker compose logs -f <service>` | Follow a container's output |
| `docker compose exec <service> <command>` | Run a command inside a running container |
| `docker compose stop` / `start` | Pause and resume without removing anything |
| `docker compose down` | Remove containers and networks; keeps the volumes |
| `docker compose down -v` | Also delete the volumes (all history and cached graphs) |
| `docker compose up -d --scale math-service=3` | Run three copies of a service |
| `docker compose --profile monitoring up -d` | Also start Prometheus (:9090) and Grafana (:3000) |
| `docker compose --profile tools up -d` | Also start Adminer (:8081) |
| `docker compose run --rm db-backup` | Back up the database to `backups\` |
| `docker compose run --rm smoke-test` | Test every tool end to end |
| `docker compose run --rm unit-tests` | Run the unit tests in a container |
| `docker compose exec cache redis-cli flushall` | Empty the graph cache |
| `docker volume ls` / `docker volume inspect calculator-app_db-data` | See where the data lives |
| `docker network ls` / `docker network inspect calculator-app_cache` | See the networks and who is on them |
| `docker stats` | Live CPU and memory per container |
| `kubectl apply -f k8s/` | Create or update everything on Kubernetes |
| `kubectl kustomize deploy/overlays/ghcr` | Show the manifests that Argo CD deploys (registry images) |
| `docker compose events --filter event=die` | Watch containers stop (use it while crashing one in the chaos lab) |
| `kubectl get pods -n calc-suite` | Pod status |
| `kubectl scale deployment <name> -n calc-suite --replicas=N` | Change the number of pods |
| `kubectl rollout restart / status / undo deployment/<name> -n calc-suite` | Rolling update and rollback |
| `kubectl delete -f k8s/` | Remove the Kubernetes deployment |

## API reference

All paths go through the gateway (`http://localhost:8080`, or `:30080` on Kubernetes).

| Method and path | Body example | Service |
|---|---|---|
| `POST /api/calc/calculate` | `{"num1": 12, "num2": 4, "operation": "multiply"}` | calc-service |
| `GET /api/converter/units` | | converter-service |
| `POST /api/converter/convert` | `{"category": "length", "value": 10, "from_unit": "km", "to_unit": "mi"}` | converter-service |
| `GET /api/finance/gst/rates` | | finance-service |
| `POST /api/finance/gst` | `{"amount": 1000, "rate": 18, "mode": "exclusive", "supply": "intra"}` | finance-service |
| `POST /api/finance/emi` | `{"principal": 500000, "annual_rate": 9, "tenure": 5, "tenure_unit": "years"}` | finance-service |
| `GET /api/student/formulas` | | student-service |
| `POST /api/student/cgpa` | `{"direction": "to_percentage", "value": 8.2, "formula": "mitadt"}` | student-service |
| `POST /api/student/grades` | `{"subjects": [{"name": "Maths", "marks": 78, "max_marks": 100, "credits": 4}]}` | student-service |
| `POST /api/student/attendance` | `{"attended": 42, "total": 60, "required": 75}` | student-service |
| `GET /api/math/functions` | | math-service |
| `POST /api/math/evaluate` | `{"expression": "sin(30) + 2^10", "angle": "deg"}` | math-service |
| `POST /api/math/plot2d` | `{"functions": ["sin(x)", "x^2/8 - 2"], "x_min": -10, "x_max": 10}` | math-service |
| `POST /api/math/plot3d` | `{"mode": "surface", "expression": "x^2 - y^2", "x_min": -3, "x_max": 3, "y_min": -3, "y_max": 3}` | math-service |
| `POST /api/math/plot3d` | `{"mode": "curve", "expr_x": "cos(t)", "expr_y": "sin(t)", "expr_z": "t/5", "t_min": 0, "t_max": 25}` | math-service |
| `POST /api/math/plot3d` | `{"mode": "parametric", "expr_x": "(3 + cos(v))cos(u)", "expr_y": "(3 + cos(v))sin(u)", "expr_z": "sin(v)"}` | math-service |
| `POST /api/math/calculus` | `{"expression": "x^3 - 3x", "x0": 2, "a": -2, "b": 2}` | math-service |
| `POST /api/math/statistics` | `{"x": "1, 2, 3, 4", "y": "3, 5, 7, 9", "mode": "sample"}` | math-service |
| `GET /api/math/solids` | | math-service |
| `POST /api/math/solid` | `{"shape": "cylinder", "dims": {"r": 3, "h": 10}, "unit": "cm"}` | math-service |
| `POST /api/matrix/matrix` | `{"operation": "inverse", "a": [["2", "-1"], ["1", "3"]]}` | matrix-service |
| `POST /api/matrix/vector3d` | `{"a": [1, 2, 3], "b": [4, -1, 2]}` | matrix-service |
| `GET /api/history/records?limit=20` | | history-service |
| `DELETE /api/history/records` | | history-service |
| `GET /api/history/stats` | | history-service |
| `POST /api/solver/ask` | `{"text": "EMI for 5 lakh at 9% for 3 years"}` | solver-service (answer, details, steps, `used` services, how to open the tool) |
| `GET /api/solver/examples` | | solver-service |
| `POST /api/solver/derivative` | `{"expression": "x^2 sin(x)", "at": "1"}` | solver-service (steps) |
| `POST /api/solver/integral` | `{"expression": "x e^x", "lower": "0", "upper": "2"}` (leave the limits out for an indefinite integral) | solver-service (steps) |
| `POST /api/solver/equation` | `{"equation": "x^2 - 5x + 6 = 0"}` | solver-service (steps) |
| `POST /api/solver/matrix-steps` | `{"operation": "inverse", "matrix": [["2","1"],["5","3"]]}` (also `determinant`, `rref`, `solve` with `"constants"`) | solver-service (steps) |
| `POST /api/solver/emi-steps` | `{"principal": 500000, "annual_rate": 9, "tenure": 3, "tenure_unit": "years"}` | solver-service (steps) |
| `POST /api/solver/gst-steps` | `{"amount": 2499, "rate": 18, "mode": "exclusive"}` | solver-service (steps) |
| `POST /api/<name>/chaos` | `{"mode": "crash"}`, `{"mode": "slow", "seconds": 30}`, `{"mode": "errors"}`, `{"mode": "heal"}`; `GET` shows the state. Needs `CHAOS_ENABLED=true`. Through the gateway `/api/history/chaos` allows only this route | every service |
| `GET /api/<name>/health` | | each service (`/api/history/ready` also checks the database, `/api/math/ready` the cache) |

Matrix operations: `determinant`, `inverse`, `transpose`, `rank`, `trace`, `power`, `rref`,
`eigen`, `scalar` (with `"scalar": "1/2"`), and with a second matrix `b`: `add`, `subtract`,
`multiply`, `solve`. Cells can be whole numbers, decimals or fractions written as strings (`"3/4"`).
Calculator operations: `add`, `subtract`, `multiply`, `divide`, `power`, `modulus`, `percent_of`.
GST `mode` is `exclusive` (amount is before GST) or `inclusive` (amount already includes GST);
`supply` is `intra` (CGST + SGST) or `inter` (IGST). The GST slabs are the ones in force since the
reform of 22 September 2025. Each service's `/metrics` page is only reachable inside Docker (by
Prometheus); through the gateway it returns 404. Solver answers are saved in the history under the tool name `solver`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `port is already allocated` | Another container or program uses the port: `docker compose down --remove-orphans`, then `docker compose up -d`, or change the port in `.env` (`APP_PORT`, `GRAFANA_PORT`, `PROMETHEUS_PORT`, `ADMINER_PORT`) |
| Old page still showing after the upgrade | Hard refresh with Ctrl+F5 |
| The page says a service isn't responding | `docker compose ps`, then `docker compose logs <service>` |
| `secret file ... db_password.txt not found` | The `secrets` folder is missing: create `secrets\db_password.txt` containing just `calc_password` |
| `history-service` can't log in to the database | `secrets\db_password.txt` must hold the password the volume was created with (`calc_password`), on one line. Or reset with `docker compose down -v` (deletes history) |
| A graph looks out of date after you changed math-service's code | It came from the cache: `docker compose exec cache redis-cli flushall` (or raise `VERSION` in `app.py`, which is part of every cache key) |
| The Ask box says solver-service isn't responding | `docker compose ps`, then `docker compose logs solver-service`. The container may be restarting after a crash from the chaos lab |
| The steps appear all at once, with no animation | The system has *reduce motion* switched on (Windows: Settings, Accessibility, Visual effects, Animation effects). That is on purpose |
| The steps stop appearing | Press **Play**, or **Show all**. Scrolling by hand stops the page from following the steps |
| The chaos lab says it is switched off | Put `CHAOS_ENABLED=true` in `.env` and run `docker compose up -d`; on Kubernetes set it in `k8s/01-config.yaml` and restart the pods |
| Grafana shows *No data* | Wait 30 seconds and use the app; check http://localhost:9090/targets shows the services as UP |
| `smoke-test` says *pull access denied* | Build first: `docker compose build` |
| Kubernetes pods show `ErrImageNeverPull` | Run `docker compose build`, and make sure the Kubernetes cluster type is **kubeadm** (a kind cluster keeps its own image store) |
| Kubernetes `db-0` stays `Pending` | `kubectl describe pod db-0 -n calc-suite`; check that a storage class exists with `kubectl get storageclass` |
| http://localhost:30080 doesn't open | `kubectl get svc gateway -n calc-suite` should show `80:30080/TCP`; as a fallback run `kubectl port-forward svc/gateway 8090:80 -n calc-suite` and open http://localhost:8090 |
