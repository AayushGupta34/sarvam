# Deploying the website

Frontend on Vercel, backend on Render, database on Neon. The backend must run as one instance, because live frames are held in memory.

## 1. Push the code

In GitHub Desktop, commit and publish this repository. Check that `.env` is not in the list of changed files.

## 2. Database

1. Create a free project at neon.tech.
2. Copy the connection string and change its start to `postgresql+psycopg://`.

Without this step, history is lost whenever the backend restarts.

## 3. Backend on Render

1. render.com > New > Web Service > pick the repository.
2. Language: Docker. Root Directory: `ems-vision-sarvam-kivi`.
3. Instance type: Starter or higher. The free tier sleeps when idle, which drops camera connections.
4. Generate a long random access code, for example with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

5. Add these environment variables:

| Name | Value |
| :--- | :--- |
| `SARVAM_API_KEY` | your key |
| `DATABASE_URL` | from step 2 |
| `APP_ACCESS_TOKEN` | the access code |
| `ALLOW_PRIVATE_FEED_URLS` | `false` |
| `CORS_ORIGINS` | leave for now |

6. Deploy, then open `https://<your-service>.onrender.com/api/health`. It should show `"status": "ok"` and `"demo_mode": false`.

## 4. Frontend on Vercel

1. vercel.com > Add New > Project > pick the repository.
2. Root Directory: `ems-vision-sarvam-kivi/frontend`.
3. Add `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com`, with no trailing slash.
4. Deploy and copy the site address.

## 5. Connect the two

1. In Render, set `CORS_ORIGINS` to the Vercel address, for example `https://ems-vision.vercel.app`, and save.
2. Open the site and enter the access code.

## 6. Check it

1. Rework station: analyze a board, change language, play the steps.
2. Feeds and sensors: Connect device > This device's camera > allow the camera.
3. Kivi voice space: record a sentence.

## Factory hardware

On a computer on the factory network, clone this repository, install `requirements.txt`, set `APP_ACCESS_TOKEN`, and run the command the site shows for that feed, using `wss://<your-service>.onrender.com` as the server. No inbound ports are needed.

## Known limits

- Kivi dictionary edits are stored in the container and reset on redeploy. Attach a Render disk at `/srv/backend/data/kivi_space` to keep them, after copying the seed files there.
- A captured golden frame is held in memory and has to be retaken after a restart.
- RTSP pulled by the server needs a publicly reachable camera. Otherwise use the agent.
- The image has no PyTorch. To run YOLO, add `requirements-ml.txt` and at least 2 GB of memory.
