# Deploying Tastes of India to Render

The project ships with a `render.yaml` blueprint, so deployment is mostly one-click.

## 1. Push the project to GitHub

```bash
cd ~/Desktop/tastes-of-india
git init
git add .
git commit -m "Initial Tastes of India site"
# Create a new empty repo on GitHub (via github.com or `gh repo create`)
git branch -M main
git remote add origin https://github.com/<your-username>/tastes-of-india.git
git push -u origin main
```

## 2. Create the Render service

1. Go to https://dashboard.render.com and sign in.
2. Click **New +** → **Blueprint**.
3. Connect your GitHub account (if not already) and select the
   `tastes-of-india` repo.
4. Render will detect `render.yaml` and show a single web service named
   `tastes-of-india`. Click **Apply**.
5. Wait ~3–5 minutes for the first build. The build command installs Python
   dependencies, initializes the SQLite DB, and seeds all 50 recipes.
6. Once live, Render will give you a URL like
   `https://tastes-of-india.onrender.com`.

## 3. About the recipe agent

The background agent (`agent/recipe_agent.py`) is a long-running process and
is **not** run on Render's free web tier (which sleeps after inactivity and
uses an ephemeral filesystem). Two options:

- **Keep running it locally** on your Mac in a second Terminal tab:
  ```bash
  cd ~/Desktop/tastes-of-india
  source venv/bin/activate
  python agent/recipe_agent.py
  ```
- **Upgrade to a paid Render plan** and add a Background Worker service
  to `render.yaml` with a persistent disk mounted at `/opt/render/project/src/instance`.

## 4. Notes on Render's free tier

- Free web services sleep after ~15 minutes of inactivity; first request after
  a sleep takes ~30s to wake.
- The SQLite file in `instance/` is ephemeral — it is re-seeded on each deploy
  via the `buildCommand`. Saved menus created by users will be lost on redeploy.
  For persistence, upgrade to a Starter plan and attach a Render Disk at
  `/opt/render/project/src/instance`.
