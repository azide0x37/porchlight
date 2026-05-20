PROJECT := porchlight
RELEASE_REPO := azide0x37/porchlight
VERSION := $(shell tr -d '[:space:]' < VERSION)
DIST := dist
PACKAGE_ROOT := $(DIST)/$(PROJECT)-$(VERSION)
TARBALL := $(DIST)/$(PROJECT)-$(VERSION).tar.gz

.PHONY: test package clean verify

test:
	uv run python -m unittest discover -s tests
	sh -n bin/install.sh bin/uninstall.sh bin/update.sh bin/doctor.sh bin/render-units.sh bin/scan-now.sh bin/porchlightctl bin/setup-ap.sh bin/setup-apply.sh
	stage="$$(mktemp -d)"; MUSTER_ROOT="$$stage" ./bin/install.sh; MUSTER_ROOT="$$stage" ./bin/doctor.sh

verify: test package

package: clean
	mkdir -p "$(PACKAGE_ROOT)"
	cp -R README.md AGENTS.md CODEX_TASK.md MUSTER.md RELEASE.md SECURITY.md VERSION pyproject.toml uv.lock muster.yaml Makefile bin etc src systemd tests "$(PACKAGE_ROOT)/"
	find "$(PACKAGE_ROOT)" -name __pycache__ -type d -prune -exec rm -rf {} +
	chmod 0755 "$(PACKAGE_ROOT)"/bin/*.sh "$(PACKAGE_ROOT)"/bin/porchlightctl "$(PACKAGE_ROOT)"/src/porchlight-ha-mqtt-bridge "$(PACKAGE_ROOT)"/src/porchlight-scan "$(PACKAGE_ROOT)"/src/porchlight-render "$(PACKAGE_ROOT)"/src/porchlight-health "$(PACKAGE_ROOT)"/src/porchlight-web
	COPYFILE_DISABLE=1 tar --no-xattrs -C "$(DIST)" -czf "$(TARBALL)" "$(PROJECT)-$(VERSION)"
	if command -v sha256sum >/dev/null 2>&1; then sha256sum "$(TARBALL)" | awk '{print $$1}' > "$(TARBALL).sha256"; else shasum -a 256 "$(TARBALL)" | awk '{print $$1}' > "$(TARBALL).sha256"; fi
	cp bin/install.sh "$(DIST)/install.sh"
	chmod 0755 "$(DIST)/install.sh"
	printf '{\n' > "$(DIST)/manifest.json"
	printf '  "project": "%s",\n' "$(PROJECT)" >> "$(DIST)/manifest.json"
	printf '  "version": "%s",\n' "$(VERSION)" >> "$(DIST)/manifest.json"
	printf '  "artifact": "%s",\n' "$(PROJECT)-$(VERSION).tar.gz" >> "$(DIST)/manifest.json"
	printf '  "artifact_url": "https://github.com/%s/releases/download/v%s/%s",\n' "$(RELEASE_REPO)" "$(VERSION)" "$(PROJECT)-$(VERSION).tar.gz" >> "$(DIST)/manifest.json"
	printf '  "sha256": "%s",\n' "$$(cat "$(TARBALL).sha256")" >> "$(DIST)/manifest.json"
	printf '  "installer": "install.sh"\n' >> "$(DIST)/manifest.json"
	printf '}\n' >> "$(DIST)/manifest.json"

clean:
	rm -rf "$(DIST)"
