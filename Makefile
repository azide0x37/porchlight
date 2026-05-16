PROJECT := porchlight
VERSION := $(shell tr -d '[:space:]' < VERSION)
DIST_DIR := dist
PACKAGE_ROOT := $(DIST_DIR)/$(PROJECT)-$(VERSION)

.PHONY: test package clean verify

test:
	uv run python -m unittest discover -s tests
	sh -n bin/install.sh bin/uninstall.sh bin/update.sh bin/doctor.sh bin/render-units.sh
	stage="$$(mktemp -d)"; STAGE_ROOT="$$stage" ./bin/install.sh; STAGE_ROOT="$$stage" ./bin/doctor.sh

verify: test package

package: clean
	mkdir -p "$(PACKAGE_ROOT)"
	cp -R README.md AGENTS.md CODEX_TASK.md MUSTER.md RELEASE.md SECURITY.md VERSION pyproject.toml uv.lock muster.yaml Makefile bin etc src systemd tests "$(PACKAGE_ROOT)/"
	find "$(PACKAGE_ROOT)" -name __pycache__ -type d -prune -exec rm -rf {} +
	chmod 0755 "$(PACKAGE_ROOT)"/bin/*.sh "$(PACKAGE_ROOT)"/src/porchlight-ha-mqtt-bridge
	cd "$(DIST_DIR)" && tar -czf "$(PROJECT)-$(VERSION).tar.gz" "$(PROJECT)-$(VERSION)"
	shasum -a 256 "$(DIST_DIR)/$(PROJECT)-$(VERSION).tar.gz" > "$(DIST_DIR)/$(PROJECT)-$(VERSION).tar.gz.sha256"
	printf '{"version":"%s","archive":"%s","sha256":"%s"}\n' "$(VERSION)" "$(PROJECT)-$(VERSION).tar.gz" "$$(awk '{print $$1}' "$(DIST_DIR)/$(PROJECT)-$(VERSION).tar.gz.sha256")" > "$(DIST_DIR)/manifest.json"

clean:
	rm -rf "$(DIST_DIR)"
