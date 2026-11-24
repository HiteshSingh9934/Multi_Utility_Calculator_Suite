# Deploying from the registry (CD)

`k8s/` runs images built on your own computer (`imagePullPolicy: Never`). This folder is the
other way: the pipeline builds, scans and publishes the images to GitHub Container Registry, and
Argo CD keeps the cluster equal to what is in Git.

```
git push main ─▶ CI: tests, lint, build + smoke test
                 CD: Trivy scan ─▶ push ghcr.io/<you>/calculator-app/<service>:sha-1a2b3c4 (+ SBOM)
                     commit "Deploy 1a2b3c4" changes newTag in deploy/overlays/ghcr/kustomization.yaml
                 Argo CD sees the commit ─▶ rolling update of the cluster
```

| Path | What it is |
|---|---|
| `deploy/overlays/ghcr/kustomization.yaml` | The manifests from `k8s/` with registry image names and tags. The pipeline edits the `newTag` lines. |
| `deploy/argocd/application.yaml` | The Argo CD Application: watch this overlay, sync automatically, undo manual changes. |

## One-time setup

1. **Push the repository to GitHub.** The first push to `main` publishes the nine images.
2. **Let the cluster pull them.** In GitHub, open each package (Packages, `calculator-app/...`)
   and set its visibility to Public, or create an image pull secret in the `calc-suite` namespace.
3. **Create the database secret.** It is the only thing that is not in Git:
   `kubectl create namespace calc-suite` and then edit `k8s/01-config.yaml` as in the main README,
   or create `db-credentials` yourself with `kubectl create secret generic`.
4. **Install Argo CD** (see argo-cd.readthedocs.io) and apply the application:
   `kubectl apply -f deploy/argocd/application.yaml`.

Look at it with `kubectl -n argocd port-forward svc/argocd-server 8081:443`, then open https://localhost:8081.

## Try it by hand, without Argo CD

```bash
kubectl kustomize deploy/overlays/ghcr | less      # see what would be applied
kubectl apply -k deploy/overlays/ghcr              # apply it (replace OWNER in the file first)
```

## Roll back

Revert the "Deploy ..." commit in Git. Argo CD rolls the cluster back to that build.
