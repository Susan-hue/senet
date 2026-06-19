# Senet Frontend

React + TypeScript + Vite client for the Senet platform.

## Run locally

```bash
cd frontend
npm install
cp .env.example .env          # or use the included .env for local dev
npm run dev
```

The dev server runs at http://localhost:5173. API requests are proxied to the backend URL in `VITE_API_URL` (default: http://localhost:8000).

Start the backend from `../backend` before testing API integration.
