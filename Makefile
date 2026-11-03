.PHONY: dev test seed

dev:
	python -m uvicorn backend.app.main:app --reload --port 8000 & npm run dev

test:
	cd backend && python -m pytest -q

seed:
	python -c "from backend.app.db import Base, engine; Base.metadata.create_all(engine)"
