# EMS Vision

Post-assembly PCB inspection with vernacular rework guidance for Indian EMS factories, built on Sarvam's APIs.

- `edge-sensing/`: registration, golden-template comparison, BOM and Gerber mapping, X-ray void measurement, root-cause rules, dataset tools, and `agent.py` for factory-side feeds.
- `backend/`: FastAPI service with the Sarvam integration, Kivi voice pipeline, feeds and history.
- `frontend/`: Next.js site with the rework station, feeds and sensors, and Kivi voice space.

Pass/fail is decided in code. The model only ranks known causes and formats text.

## Run locally

Windows, from this folder:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r requirements-ml.txt
```

Second line is optional and only matters once trained weights exist at `edge-sensing/weights/pcb_yolo11n.pt`.

Terminal 1:

```bash
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. `SARVAM_API_KEY` is read from `.env` here or in the parent folder. With no key the site runs in demo mode: stored translations, a test tone instead of speech, and a canned transcript.

## Tests and evaluation

```bash
.venv\Scripts\python -m pytest
.venv\Scripts\python edge-sensing\datasets\download_and_verify.py deeppcb
.venv\Scripts\python edge-sensing\evaluate_pipeline.py --deeppcb edge-sensing\datasets\raw\deeppcb
```

`--live-kivi` adds a spoken WER run through Sarvam and spends credits. Tests never call Sarvam.

## Connecting feeds

Any number of feeds can run at once. Add them from Feeds and sensors > Connect device.

| Source | How it reaches the site |
| :--- | :--- |
| Webcam or USB microscope | Browser sends frames. Needs HTTPS or localhost. |
| Public IP camera | Server pulls the MJPEG, snapshot or RTSP address. |
| GigE, private RTSP, thermal, X-ray | `edge-sensing/agent.py` on the factory network pushes frames outward. |
| Fixture sensors | USB serial from Chrome or Edge, or the agent. One JSON object per line. |
| PLC trigger | Agent polls Modbus TCP or OPC-UA and starts an inspection. |

The site shows the agent command for each feed. A live camera needs "Capture golden" on a known-good board before "Inspect". Regions are then reported by position, since there is no BOM for that board yet.

## Deployment

See [DEPLOY.md](DEPLOY.md).
