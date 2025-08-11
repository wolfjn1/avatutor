SHELL := /bin/bash

.PHONY: install lint typecheck format test unit docker-build compose-up compose-down

install:
	python -m pip install --upgrade pip
	pip install -e .[dev]

lint:
	ruff check .
	black --check .

format:
	black .
	ruff check --fix .

typecheck:
	mypy apps/api apps/sidecar opsctl policy

test:
	pytest -q

unit: test

docker-build:
	docker build -f infrastructure/Dockerfile.api -t ai-tutor-autopilot:latest .

compose-up:
	docker compose -f infrastructure/docker-compose.yml up -d --build

compose-down:
	docker compose -f infrastructure/docker-compose.yml down -v


