.PHONY: dev test seed reset

dev:
	cd backend && python -m uvicorn app.main:app --reload --port 8000 & npm run dev

test:
	cd backend && python -m pytest -q

seed:
	cd backend && python -m seed

reset:
	cd backend && python -c "from app.db import Base, engine; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"
