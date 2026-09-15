include ports.env
export UI_PORT API_PORT DB_PORT VITE_PORT
.DEFAULT_GOAL := help
.SILENT:

.PHONY: help up seed verify test down logs dev-ui frontend-deps browser-deps azure-prepare azure-validate azure-deploy azure-update azure-configure azure-seed azure-status azure-verify azure-repair-network

help:
	sh scripts/output.sh help

up:
	sh scripts/output.sh section "Build and deploy"
	sh scripts/dev.sh up

seed:
	sh scripts/output.sh section "Import catalogue snapshot"
	sh scripts/dev.sh seed

verify: frontend-deps browser-deps
	sh scripts/output.sh section "Verify cancellation and database"
	sh scripts/test-tunnel.sh
	sh scripts/dev.sh verify
	sh scripts/output.sh section "Verify browser workflows"
	cd frontend && npm run test:e2e

test:
	sh scripts/output.sh section "Shell workflow checks"
	for script in scripts/*.sh; do sh -n "$$script"; done
	sh scripts/test-workflow.sh
	sh scripts/output.sh section "Backend checks"
	cd backend && uv run --frozen ruff check . && uv run --frozen pytest
	sh scripts/output.sh section "Frontend checks"
	cd frontend && npm ci && npm run lint && npm run build && npm test

down:
	sh scripts/output.sh section "Delete local cluster and database"
	sh scripts/dev.sh down

logs:
	sh scripts/output.sh section "Application logs"
	sh scripts/dev.sh logs

frontend-deps:
	sh scripts/output.sh section "Frontend dependencies"
	cd frontend && npm ci

browser-deps: frontend-deps
	sh scripts/output.sh section "Browser runtime"
	cd frontend && npx playwright install chromium

dev-ui: frontend-deps
	sh scripts/output.sh section "Frontend development server"
	cd frontend && npm run dev

azure-prepare:
	sh scripts/azure.sh prepare

azure-validate:
	sh scripts/azure.sh validate

azure-deploy:
	sh scripts/azure.sh deploy

azure-update:
	sh scripts/azure.sh update

azure-configure:
	sh scripts/azure.sh configure

azure-seed:
	sh scripts/azure.sh seed

azure-status:
	sh scripts/azure.sh status

azure-verify: frontend-deps browser-deps
	sh scripts/azure.sh verify

azure-repair-network:
	sh scripts/azure.sh repair-network
