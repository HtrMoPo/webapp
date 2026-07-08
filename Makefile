.PHONY: build up down logs db-pull db-shell list-users set-admin

COMPOSE = docker compose

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

# Copies the SQLite database out of the running container into ./data/,
# in case the ./data volume mount isn't already in use on the host.
db-pull:
	docker cp $$($(COMPOSE) ps -q app):/data/htrmopo-app.db ./data/htrmopo-app.db
	@echo "Database copied to ./data/htrmopo-app.db"

db-shell:
	sqlite3 ./data/htrmopo-app.db

# Lists known users (id, Zenodo identity, admin flag) to find the id to pass to set-admin.
list-users:
	$(COMPOSE) exec app python -m app.scripts.manage_users list

# Grants or revokes admin status (needed to trigger an on-demand catalog
# refresh from the UI). Usage: make set-admin ID=1 [ADMIN=false]
ADMIN ?= true
set-admin:
	@if [ -z "$(ID)" ]; then echo "Usage: make set-admin ID=<user id> ADMIN=true|false"; exit 2; fi
	$(COMPOSE) exec app python -m app.scripts.manage_users set-admin $(ID) $(ADMIN)
