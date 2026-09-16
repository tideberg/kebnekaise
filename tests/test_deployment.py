import json
import unittest
from pathlib import Path

from scripts.check_node_runtime import latest_same_major, version_tuple


ROOT = Path(__file__).resolve().parents[1]


class DeploymentPolicyTests(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text()

    def test_production_only_starts_collector(self):
        unit = self.read("deploy/systemd/kebnekaise.service")
        pilot = self.read("deploy/systemd/pilot/kebnekaise.service.d/override.conf")
        self.assertIn("/pilot.sqlite3 collect\n", pilot)
        self.assertIn("/office.sqlite3 collect\n", unit)
        self.assertNotIn("/office.sqlite3 run\n", unit)

    def test_dashboard_is_loopback_only_on_demand_and_time_limited(self):
        unit = self.read("deploy/systemd/kebnekaise-dashboard.service")
        self.assertNotIn("[Install]", unit)
        self.assertIn("RuntimeMaxSec=2h", unit)
        self.assertIn("IPAddressDeny=any", unit)
        self.assertIn("IPAddressAllow=localhost", unit)
        self.assertIn(" serve", unit)

    def test_matter_services_are_loopback_only_and_do_not_receive_ha_tokens(self):
        matter_unit = self.read("deploy/systemd/kebnekaise-matter.service")
        pilot = self.read("deploy/systemd/pilot/kebnekaise.service.d/override.conf")
        self.assertIn("--listen-address 127.0.0.1", matter_unit)
        self.assertIn("/opt/node-v24.21.0-linux-arm64/bin/node", matter_unit)
        self.assertIn("EnvironmentFile=\n", pilot)
        self.assertIn("UnsetEnvironment=KEBNEKAISE_HA_TOKEN SUPERVISOR_TOKEN", pilot)
        self.assertIn("IPAddressDeny=any", pilot)
        self.assertIn("IPAddressAllow=localhost", pilot)

    def test_npm_tree_is_locked_to_registry_and_install_scripts_are_disabled(self):
        package = json.loads(self.read("deploy/matter/package.json"))
        lock = json.loads(self.read("deploy/matter/package-lock.json"))
        npmrc = self.read("deploy/matter/.npmrc")
        self.assertEqual(package["engines"]["node"], "24.21.0")
        self.assertEqual(lock["packages"][""]["engines"]["node"], "24.21.0")
        self.assertIn("ignore-scripts=true", npmrc)
        self.assertIn("save-exact=true", npmrc)
        for name, metadata in lock["packages"].items():
            if not name:
                continue
            self.assertTrue(metadata.get("resolved", "").startswith("https://registry.npmjs.org/"), name)
            self.assertTrue(metadata.get("integrity", "").startswith("sha512-"), name)

    def test_ssh_policy_is_key_only_and_has_no_remote_forwarding(self):
        policy = self.read("deploy/ssh/99-kebnekaise.conf")
        for setting in (
            "AuthenticationMethods publickey",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "PermitRootLogin no",
            "AllowGroups kebnekaise-admin",
            "AllowTcpForwarding local",
            "AllowStreamLocalForwarding no",
            "PermitOpen 127.0.0.1:8840 127.0.0.1:5580",
            "GatewayPorts no",
            "PermitTunnel no",
        ):
            self.assertIn(setting, policy)

    def test_node_runtime_version_check_is_exact_and_same_major(self):
        releases = [{"version": "v25.1.0"}, {"version": "v24.20.1"}, {"version": "v24.21.0"}]
        self.assertEqual(version_tuple("24.21.0"), (24, 21, 0))
        self.assertEqual(latest_same_major(releases, "24.19.0"), (24, 21, 0))
        with self.assertRaises(ValueError):
            version_tuple("24.x")


if __name__ == "__main__":
    unittest.main()
