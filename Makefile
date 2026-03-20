SHELL  := /bin/bash
VENV   := venv/bin
PYTHON := $(VENV)/python
PLIST  := $(HOME)/Library/LaunchAgents/com.frontier.linkedin-worker.plist

.DEFAULT_GOAL := help

# ── Setup ─────────────────────────────────────────────────────────────────────
.PHONY: setup
setup:          ## Full one-time setup (venv, deps, playwright, launchd)
	bash setup.sh

# ── Cookies ───────────────────────────────────────────────────────────────────
.PHONY: cookies
cookies:        ## Open browser to refresh LinkedIn session cookies
	$(PYTHON) save_cookies.py

# ── Worker ────────────────────────────────────────────────────────────────────
.PHONY: worker-start
worker-start:   ## Start the background worker via launchd
	launchctl load $(PLIST)

.PHONY: worker-stop
worker-stop:    ## Stop the background worker
	launchctl unload $(PLIST)

.PHONY: worker-restart
worker-restart: ## Restart the background worker
	launchctl unload $(PLIST) 2>/dev/null || true
	launchctl load $(PLIST)

.PHONY: worker
worker:         ## Run the worker directly in this terminal (Ctrl+C to stop)
	$(PYTHON) worker.py

.PHONY: worker-logs
worker-logs:    ## Tail live worker output
	tail -f worker.log

.PHONY: worker-status
worker-status:  ## Show whether the worker process is running
	launchctl list | grep linkedin-worker || echo "Worker not running"

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "LinkedIn Scraper — available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	    | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36mmake %-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
