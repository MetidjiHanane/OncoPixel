# Architecture

```
┌────────────────────────────┐     http://127.0.0.1:<port>      ┌──────────────────────────────────┐
│ Electron shell (main.cjs)  │ ───────────────────────────────▶ │ FastAPI backend (Python)         │
│  - starts the backend      │   X-OncoPixel-App: <launch token>│  - guard: loopback Host + token  │
│  - injects the token       │   cookie op_session (HttpOnly)   │  - api/auth, api/core, api/clinical
│  - blocks other networks   │                                  │  - services/*  exports/*  ml/*   │
│ React UI (desktop/src)     │                                  └───────┬───────────────┬──────────┘
└────────────────────────────┘                                          │               │
                                                              SQLite (WAL)      encrypted file store
                                                              metadata, log     images, masks, maps
```

## Process model

The Electron main process picks a Python interpreter (`ONCOPIXEL_PYTHON`, then `backend/.venv`, then `python3`), starts `python -m oncopixel.server`, waits for the line `ONCOPIXEL_READY <port>`, and then loads `http://127.0.0.1:<port>`. The backend serves both the API and the built interface (`desktop/dist`). Quitting the window stops the backend. In a plain browser (development) the same backend works without Electron and without the launch token.

## Security model

- The backend binds to `127.0.0.1`. A middleware rejects any `Host` that is not loopback (DNS rebinding) and, when a launch token is configured, any `/api` request without `X-OncoPixel-App`. The token is random per launch and added by Electron's `webRequest`, so other local programs and web pages cannot call the API.
- Electron cancels every request that is not to the local backend, denies permission prompts, window opening and navigation away.
- Sign-in: scrypt password hash, exponential lockout after 5 failures (30 s doubling to 15 min), session cookie `HttpOnly`, `SameSite=Strict`.
- At rest: patient fields in SQLite and every image, mask, heat map and uncertainty map are encrypted with Fernet. The vault key is stored in the OS keychain (`keyring`), else in a `0600` file in the data folder, else taken from `ONCOPIXEL_VAULT_KEY`. This protects against casual access to the data folder; it does not protect an unlocked, signed-in session.
- No telemetry, no update check, no external fonts or scripts (fonts are bundled). The backend contains no code that opens outbound connections.
- Local activity log (sign-ins, imports, analyses, edits, exports, backups). It is for the user and is not tamper-proof.
- Backup: one `.opbackup` file (zip of a database snapshot, the encrypted files and the vault key sealed with a scrypt-derived passphrase key).

## Backend

| Module | Role |
|---|---|
| `ml/classifier.py` | Loads the classification checkpoint, validates keys, class order and strict state dict, runs flip-averaged, temperature-scaled inference and Grad-CAM |
| `ml/segmenter.py` | Your `TumorSegmenter`, unmodified |
| `ml/segmentation.py` | Service around it: derived uncertainty (six perturbations, entropy, variability, Dice stability) |
| `ml/registry.py` | Path resolution, lazy loading, state per model (`ready`, `missing`, `invalid`), CPU/MPS device choice |
| `services/importer.py` | PNG/JPG/DICOM import, series grouping, DICOM anonymization, spacing |
| `services/validation.py` | Input checks with warning codes |
| `services/analysis.py` | Orchestrates stages; per-stage skip when a model is unavailable; re-threshold; manual mask; measurements; consistency warnings |
| `services/measurements.py` | 2D measurements |
| `services/compare.py` | Two-study comparison |
| `services/repo.py` | Patients and studies, status derivation (pending, analyzed, reviewed, flagged) |
| `exports/*` | PDF (reportlab), Word (python-docx), CSV, JSON, mask PNG, NIfTI (nibabel), DICOM-SEG and SR (highdicom) |

Errors share one shape: `{"error": {"code", "message", ...}}`. The interface translates `code` to English or French. A missing model returns HTTP 409 with `code: MODEL_MISSING`, `kind`, `state`, `reason` and `path`.

## Honesty rules enforced in code

1. An analysis result is stored only if a real model produced it. If both models are unavailable the endpoint fails and stores nothing (tested in `tests/test_missing_weights.py`).
2. Classifier and segmentation are independent stages. When they disagree, the study is flagged (`model_disagreement`).
3. Derived quantities are labelled as derived: the confidence is a "model confidence estimate", the uncertainty map is "derived from perturbations".
4. Measurements carry their unit. Millimetres appear only when the spacing is known.

## Interface

React 18 + TypeScript + Vite, `react-router-dom`, no UI framework. Themes are CSS variables (dark, light, high contrast; three text sizes). `src/i18n/en.ts` and `fr.ts` hold all text; a Vitest check fails if the two differ or if a key used in the source is missing.

## Data folder

macOS: `~/Library/Application Support/OncoPixel` (override with `ONCOPIXEL_DATA_DIR`): `oncopixel.db`, `files/` (encrypted), `exports/`, and `vault.key` only when the keychain is unavailable.
