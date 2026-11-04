.PHONY: install dev test lint build routes check

install:
	npm ci

dev:            ## http://localhost:5173 — MSW bật, KHÔNG cần backend chạy
	npm run dev

test:
	npx vitest run

lint:
	npx eslint . --max-warnings 0 && npx prettier --check src tests && npx tsc -b

build:          ## VITE_MSW=0 — bundle production KHÔNG được chứa msw
	VITE_MSW=0 npm run build

routes:         ## sinh lại src/routeTree.gen.ts sau khi thêm/xoá file route
	npx tsr generate

check: lint test   ## chạy trước khi mở merge request
