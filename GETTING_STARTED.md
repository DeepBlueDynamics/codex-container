# Getting Started (Zip Download)

This guide is for a quick, no-git setup using ZIP downloads. You will download two repos, unzip them, open a terminal in the folder, then run the scripts.

## What you will install
- `codex-container` (zip download)
- `gnosis-crawl` (zip download)
- Docker Desktop (required)

## 1) Download and unzip the repos

Codex container (zip):
- https://github.com/deepbluedynamics/codex-container/archive/refs/heads/main.zip

Gnosis-crawl (zip):
- https://github.com/deepbluedynamics/gnosis-crawl/archive/refs/heads/main.zip

Unzip both so you have two folders, side-by-side, for example:
- `C:\Users\you\Downloads\codex-container`
- `C:\Users\you\Downloads\gnosis-crawl`

Windows tip: Right-click the zip file and choose **Extract to...** so you control the folder location.

Note: GitHub zip downloads include a nested folder (e.g., `codex-container-main\codex-container-main`). Use the **inner** folder that contains `scripts/`, `MCP/`, and `README.md`.

## 2) Open a terminal in the codex-container folder

Windows:
- Open File Explorer → open the `codex-container` folder
- Right-click inside the folder → **Open in Terminal**

macOS:
- Finder → Utilities → Terminal
- `cd` to the folder, e.g.:
  `cd ~/Downloads/codex-container`

Linux:
- Open a terminal, then `cd` to the folder

## 3) Windows: allow script execution (PowerShell)

Windows will often block scripts by default. Run these once (current user only):

```powershell
Unblock-File -Path .\scripts\gnosis-container.ps1
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

If your company policy blocks this, you will need IT to allow it.

## 4) Build and run Codex container

From the `codex-container` folder:

```powershell
.\scripts\gnosis-container.ps1 -Install
```

This builds and runs the container on first use. Use the same script for future runs.

## 5) Start gnosis-crawl (separate folder)

Open a new terminal in the `gnosis-crawl` folder and run:

```powershell
./deploy.ps1 -Target local
```

Docker Desktop must be running.

## 6) Verify services

- Codex container should be running in your terminal session
- Gnosis-crawl should be running via Docker

If you see a Docker network error like `codex-network not found`, create it once:

```powershell
docker network create codex-network
```

## Next steps

- Start a session and run a simple prompt
- Save a page and search it using the built-in search tools
- Index a PDF and query it by page number

If you want a walkthrough of the first search demo and PDF indexing demo, say the word and I will add it.
