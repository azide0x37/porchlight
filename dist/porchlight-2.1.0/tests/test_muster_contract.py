from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MusterContractTest(unittest.TestCase):
    def test_systemd_units_call_current_release_bin(self):
        service = (ROOT / "systemd/porchlight-ha-mqtt-bridge.service").read_text(encoding="utf-8")
        timer = (ROOT / "systemd/porchlight-ha-mqtt-bridge.timer").read_text(encoding="utf-8")

        self.assertIn("ExecStart=/opt/porchlight/current/bin/porchlight-ha-mqtt-bridge --apply --once", service)
        self.assertIn("EnvironmentFile=-/etc/porchlight/porchlight.env", service)
        self.assertIn("EnvironmentFile=-/etc/porchlight/porchlight.mqtt.env", service)
        self.assertIn("Unit=porchlight-ha-mqtt-bridge.service", timer)
        scan = (ROOT / "systemd/porchlight-scan.service").read_text(encoding="utf-8")
        scan_timer = (ROOT / "systemd/porchlight-scan.timer").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/opt/porchlight/current/bin/porchlight-scan --apply --mode scan", scan)
        self.assertIn("AF_NETLINK", scan)
        self.assertIn("Unit=porchlight-scan.service", scan_timer)
        for name in [
            "porchlight-discover.timer",
            "porchlight-deep-scan.timer",
            "porchlight-render.service",
            "porchlight-render.timer",
            "porchlight-health.service",
            "porchlight-health.timer",
            "porchlight-web.service",
            "porchlight-setup-ap.service",
            "porchlight-setup-apply.service",
            "porchlight-setup-apply.path",
        ]:
            self.assertTrue((ROOT / "systemd" / name).is_file(), name)

    def test_readme_self_certifies_muster_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in [
            "## Self-Certification",
            "curl -fsSL https://github.com/azide0x37/porchlight/releases/latest/download/install.sh | sudo sh",
            "azide0x37/porchlight-dashboard",
            "systemd owns lifecycle",
            "runtime under `/opt/porchlight/releases/<version>`",
            "updater verifies and rolls back",
            "make test",
            "make package",
            "install.sh --appliance",
            "/api/setup/*",
        ]:
            self.assertIn(text, readme)

    def test_muster_yaml_names_lifecycle_artifacts(self):
        muster = (ROOT / "muster.yaml").read_text(encoding="utf-8")
        for text in [
            "T2R6.home-assistant-mqtt-bridge",
            "T3C1.edge-appliance-bundle",
            "R4.state-ledger",
            "bin/install.sh",
            "bin/update.sh",
            "bin/uninstall.sh",
            "bin/doctor.sh",
            "make package",
            "src/porchlight/webroot",
            "src/porchlight/settings.py",
            "porchlight-setup-apply.path",
        ]:
            self.assertIn(text, muster)

    def test_release_manifest_shape_matches_dvd_ingester_reference(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for text in [
            '"project"',
            '"artifact"',
            '"artifact_url"',
            '"sha256"',
            '"installer"',
            "cp bin/install.sh",
            "releases/download/v",
        ]:
            self.assertIn(text, makefile)

    def test_installer_and_doctor_cover_mqtt_adapter_dependency(self):
        install = (ROOT / "bin/install.sh").read_text(encoding="utf-8")
        doctor = (ROOT / "bin/doctor.sh").read_text(encoding="utf-8")

        self.assertIn("mosquitto-clients", install)
        self.assertIn("nmap", install)
        self.assertIn("arp-scan", install)
        self.assertIn("network-manager", install)
        self.assertIn("avahi-daemon", install)
        self.assertIn("--appliance", install)
        self.assertIn("MUSTER_SKIP_PACKAGES", install)
        self.assertIn("HA_MQTT_ENABLE", doctor)
        self.assertIn("mqtt publish adapter available", doctor)
        self.assertIn("sqlite ledger created", doctor)
        self.assertIn("dashboard snapshot rendered", doctor)

    def test_dashboard_assets_are_packaged_and_runtime_json_backed(self):
        webroot = ROOT / "src/porchlight/webroot"
        index = (webroot / "index.html").read_text(encoding="utf-8")
        app = (webroot / "app.js").read_text(encoding="utf-8")
        style = (webroot / "style.css").read_text(encoding="utf-8")
        web = (ROOT / "src/porchlight/web.py").read_text(encoding="utf-8")

        for path in [
            webroot / "index.html",
            webroot / "app.js",
            webroot / "style.css",
            webroot / "manifest.webmanifest",
            webroot / "icon-round.png",
            webroot / "icon-192.png",
            webroot / "icon-512.png",
            webroot / "apple-icon.png",
            webroot / "icon.svg",
            webroot / "fonts/inter-latin.woff2",
            webroot / "fonts/fraunces-latin.woff2",
            webroot / "fonts/jetbrains-latin.woff2",
        ]:
            self.assertTrue(path.is_file(), path)

        self.assertIn("Porchlight - LAN directory", index)
        self.assertIn("viewport-fit=cover", index)
        self.assertIn("apple-touch-icon", index)
        self.assertIn("/style.css?v=2.1.0", index)
        self.assertIn("/app.js?v=2.1.0", index)
        self.assertIn("Porchlight v2.1.0", index)
        self.assertIn("https://github.com/azide0x37/muster", index)
        self.assertIn("https://github.com/azide0x37/porchlight", index)
        self.assertIn("/status.json", app)
        self.assertIn("/hosts.json", app)
        self.assertIn("/services.json", app)
        self.assertIn("/api/setup/status", app)
        self.assertIn("renderSettings", app)
        self.assertIn("Save MQTT", app)
        self.assertIn("Network view is current.", app)
        self.assertIn("Every known host", app)
        self.assertIn("derivedServiceCounts", app)
        self.assertIn("openPorts = serviceCounts.open_ports", app)
        self.assertIn("MQTT · RTSP", app)
        self.assertIn('hostVerb = hostCount === 1 ? "speaks" : "speak"', app)
        self.assertIn('serviceVerb = matching.length === 1 ? "is" : "are"', app)
        self.assertIn("porchlight-theme", app)
        self.assertIn("prefers-color-scheme: dark", app)
        self.assertIn("nextThemeMode", app)
        self.assertIn("startViewTransition", app)
        self.assertIn("drawer-open", app)
        self.assertIn("@font-face", style)
        self.assertIn("/fonts/inter-latin.woff2", style)
        self.assertIn("font-weight: 400;", style)
        self.assertIn("height: 0.9em;", style)
        self.assertIn("flex: 1 0 auto;", style)
        self.assertIn("overflow-wrap: anywhere;", style)
        self.assertIn("overflow-x: clip;", style)
        self.assertIn(".host-row", style)
        self.assertIn(".host-title .small", style)
        self.assertIn("grid-column: 2 / -1;", style)
        self.assertIn(':root[data-theme="dark"]', style)
        self.assertIn(".fireflies", style)
        self.assertIn(".mobile-drawer", style)
        self.assertIn("@view-transition", style)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", style)
        self.assertIn("Cache-Control", web)
        self.assertIn("no-store", web)
        self.assertIn("/api/setup/mqtt", web)
        self.assertIn("update_mqtt_settings", web)
