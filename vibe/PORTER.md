# Running the Codex CLI container on Porter

This guide shows how to run the Codex CLI container as a one-off job with [Porter](https://www.porter.run). The container does not expose any ports; it just executes commands against your source tree and exits.

## Prerequisites
- Repository access that includes this `Dockerfile` and scripts.
- A Porter project with permissions to build from that repo and access any required secrets.
- Optional (needed for Option B or local testing): Docker installed locally and a container registry you can push to (examples use GitHub Container Registry at `ghcr.io`).
- Optional (needed when triggering jobs from another service): a Porter API token scoped to run jobs in your project.

## 1. Build the container image
You have two ways to provide the Codex CLI image Porter should run:

### Option A: Let Porter build from this repo
If the Porter project is connected to this repository, add a `build` block to the service. Porter will build the `Dockerfile` in-place before each run and push it to the project’s managed registry automatically.

```yaml
services:
  codex-task:
    type: job
    build:
      dockerfile: ./Dockerfile
      context: .
    command:
      - /usr/local/bin/codex_entry.sh
    args:
      - codex
      - summarize
```

Keep the command and args aligned with the task you want Codex to perform. Porter injects the freshly built image into the job without requiring a manual push.

### Option B: Build and publish yourself
From the repository root:

```bash
docker build -t ghcr.io/<org>/<app>/codex-cli-env:latest .

echo "$GITHUB_TOKEN" | docker login ghcr.io --username <github-username> --password-stdin

docker push ghcr.io/<org>/<app>/codex-cli-env:latest
```

- Replace `<org>/<app>` with your namespace.
- If you want to pin the Codex CLI version, add `--build-arg CODEX_CLI_VERSION=0.42.0` to the `docker build` command.

## 2. Create `porter.yaml`
Add a manifest at the root of the repo Porter will deploy. The example below assumes Porter builds the image (Option A). If you prefer to supply a prebuilt image (Option B), remove the `build` block and set `image:` instead.

```yaml
app:
  name: codex-cli
  platform: kubernetes

services:
  codex-task:
    type: job
    build:
      dockerfile: ./Dockerfile
      context: .
    # For a prebuilt image, delete the build block and add:
    # image: ghcr.io/<org>/<app>/codex-cli-env:latest
    command:
      - /usr/local/bin/codex_entry.sh
    args:
      - codex
      - <subcommand>
      - --flag=value
    env:
      - name: TZ
        value: UTC
      - name: CODEX_API_KEY
        valueFrom:
          secretKeyRef:
            name: codex-api
            key: token
    resources:
      cpu: 500m
      memory: 512Mi
```

Key points:
- `type: job` tells Porter to create a Kubernetes Job that runs to completion (no Service, no port).
- `command` defaults to the entrypoint helper; update `args` with the Codex CLI invocation you need (for example `codex summarize --json-e`).
- Inject credentials via `env`. In Porter, define the `codex-api` secret in the dashboard or CLI before running the job. The container entrypoint automatically maps `OPENAI_API_KEY`, `OPENAI_TOKEN`, or `openai_token` to `CODEX_API_KEY`, so existing `.env` files that already expose one of those names continue to work.
- Adjust the resource requests to match your workload.

If the Codex CLI needs repository files, make sure the repo connected to Porter contains them, or mount additional data using Porter volumes:

```yaml
    volumes:
      - name: workspace
        mountPath: /workspace
        persistentVolume:
          name: codex-workspace
```

Create the persistent volume in the Porter UI or with `porter volumes create` and populate it with your project files as needed.

## 3. Run the job from Porter
Use either the dashboard or the CLI:

```bash
porter jobs run codex-task
```

- Porter will build (or fetch) the image, create the Kubernetes Job, and stream logs.
- Inspect past runs with `porter jobs list` and fetch logs with `porter jobs logs codex-task`.

To run on a schedule, configure a trigger:

```bash
porter cron create codex-report \
  --service codex-task \
  --schedule "0 13 * * 1-5"
```

This example runs the job at 13:00 UTC every weekday.

### Trigger jobs from another service
Your web app (or any backend worker) can start the same Porter job via HTTPS; the container itself does not expose a web server.

1. Create a Porter API token in the dashboard (`Settings → API Tokens`) with access to the project that owns `codex-task`. Store it as a secret (for example `PORTER_API_TOKEN`).
2. Capture the project ID (visible in the project URL or via `porter projects list`). The job name is the service key from `porter.yaml` (`codex-task`).
3. Issue a `POST` request when you need to run Codex:

   ```bash
   curl -X POST \
     -H "Authorization: Bearer $PORTER_API_TOKEN" \
     -H "Content-Type: application/json" \
     https://dashboard.getporter.dev/api/projects/<project-id>/jobs/codex-task/run \
     -d '{}'
   ```

   - Pass a JSON body if you want to override args or inject ad-hoc env vars for that run.
4. The response includes a run ID. Poll status with `GET .../runs/<run-id>` or fetch logs with `GET .../runs/<run-id>/logs` and surface the output back to your users.

If you prefer shelling out, your service can run `porter jobs run codex-task` directly, but the REST API avoids bundling the CLI.

## 4. Updating the command or image
- Edit `args` (or add `command`) in `porter.yaml` to change what Codex executes.
- If Porter manages the build (Option A), commit the changes and rerun the job; Porter will rebuild automatically.
- If you supply a prebuilt image (Option B), rebuild and push with `docker build ... && docker push ...`, then rerun the job.

## 5. Troubleshooting
- **Job fails immediately**: check `porter jobs logs codex-task` for Codex CLI errors (authentication, arguments, etc.).
- **Authentication errors**: verify the Codex API key secret is present and mapped to `CODEX_API_KEY`.
- **Needs host services (e.g., Ollama)**: set `ENABLE_OSS_BRIDGE=1` and expose the target via reachable network; the helper script already understands `OSS_SERVER_URL`/`OLLAMA_HOST`.
- **Long-running tasks**: adjust the Porter job timeout or Kubernetes active deadline as needed with the `timeoutSeconds` field under the service.
