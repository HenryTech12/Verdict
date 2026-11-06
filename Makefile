.PHONY: install dev backend web test test-web seed reset spike

install:
	cd backend && python -m pip install -e ".[test]"
	npm ci

backend:
	cd backend && python -m uvicorn app.main:app --reload --port 8000

web:
	npm run dev

dev:
	cd backend && python -m uvicorn app.main:app --reload --port 8000 & npm run dev

test:
	cd backend && python -m pytest -q

test-web:
	npm test && npm run lint

seed:
	cd backend && python -m seed

reset:
	rm -f backend/verdict.db backend/verdict.db-wal backend/verdict.db-shm

spike:
	cd backend && python scripts/sandbox_spike.py
