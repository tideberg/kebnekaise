import io
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from scripts import view_live


class LiveViewTests(unittest.TestCase):
    def run_main(self, *args):
        with patch('sys.argv', ['view_live.py', 'user@pi.local', *args]), \
                patch('sys.stdout', new_callable=io.StringIO), \
                patch('sys.stderr', new_callable=io.StringIO):
            return view_live.main()

    def test_demo_is_rejected_before_browser_opens(self):
        response = MagicMock()
        response.__enter__.return_value = io.StringIO(json.dumps({'mode': 'demo'}))
        with patch.object(view_live.urllib.request, 'build_opener') as client:
            client.return_value.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'inte enbart riktiga datakällor'):
                view_live.dashboard_ready()

    def test_occupied_port_is_rejected_without_opening_wrong_host(self):
        with patch.object(view_live.subprocess, 'run') as start, \
                patch.object(view_live, 'tunnel_listening', return_value=True), \
                patch.object(view_live.subprocess, 'Popen') as tunnel, \
                patch.object(view_live.webbrowser, 'open') as browser:
            self.assertEqual(self.run_main(), 1)
            start.assert_not_called()
            tunnel.assert_not_called()
            browser.assert_not_called()

    def test_mini01_uses_separate_port(self):
        with patch.object(view_live.subprocess, 'run') as start, \
                patch.object(view_live, 'make_proxy') as proxy, \
                patch.object(view_live, 'tunnel_listening', return_value=False), \
                patch.object(view_live.subprocess, 'Popen') as factory, \
                patch.object(view_live, 'dashboard_ready', return_value=True), \
                patch.object(view_live.webbrowser, 'open', return_value=True) as browser:
            factory.return_value.poll.return_value = None
            factory.return_value.wait.side_effect = [KeyboardInterrupt, 0]
            self.assertEqual(self.run_main('--target', 'mini01'), 0)
            self.assertEqual(proxy.call_args.args[0], 8841)
            self.assertEqual(proxy.call_args.args[2], 8840)
            self.assertIn(f'127.0.0.1:{proxy.call_args.args[1]}:127.0.0.1:8840', factory.call_args.args[0])
            browser.assert_called_once_with('http://127.0.0.1:8841', new=2)
            self.assertEqual(start.call_args.args[0][-1],
                             'systemctl --user start kebnekaise-dashboard.service')

    def test_profile_selection_and_legacy_fallback(self):
        import argparse
        settings = {'host': 'old-pi', 'mini01': {'host': 'mini-host'}, 'rpi': {'host': 'pi-host'}}
        with patch.dict(view_live.os.environ, {}, clear=True), \
                patch.object(view_live.Path, 'exists', return_value=True), \
                patch.object(view_live.Path, 'read_text', return_value=json.dumps(settings)):
            for target, expected in [('mini01', 'mini-host'), ('rpi', 'pi-host')]:
                self.assertEqual(view_live.connection_settings(argparse.Namespace(target=target, host=None)), expected)
            self.assertEqual(view_live.connection_settings(argparse.Namespace(target='mini01', host='override')), 'override')
        with patch.dict(view_live.os.environ, {}, clear=True), \
                patch.object(view_live.Path, 'exists', return_value=True), \
                patch.object(view_live.Path, 'read_text', return_value='{"host": "old-pi"}'):
            self.assertEqual(view_live.connection_settings(argparse.Namespace(target='rpi', host=None)), 'old-pi')
            with self.assertRaisesRegex(ValueError, 'KEBNEKAISE_MINI01_HOST'):
                view_live.connection_settings(argparse.Namespace(target='mini01', host=None))

    def test_ip_override_preserves_host_identity_and_explicit_other_host(self):
        import argparse
        settings = {'rpi': {'host': 'user@pi.local', 'hostname': '192.0.2.10'}}
        with patch.dict(view_live.os.environ, {}, clear=True), \
                patch.object(view_live.Path, 'exists', return_value=True), \
                patch.object(view_live.Path, 'read_text', return_value=json.dumps(settings)):
            args = argparse.Namespace(target='rpi', host=None)
            self.assertEqual(view_live.connection_settings(args, with_options=True),
                             ('user@pi.local', ['-o', 'Hostname=192.0.2.10', '-o', 'HostKeyAlias=pi.local']))
            args.host = 'user@other-pi'
            self.assertEqual(view_live.connection_settings(args, with_options=True),
                             ('user@other-pi', []))

    def test_real_pilot_is_accepted_but_mixed_simulation_is_rejected(self):
        for providers, accepted in ((['matter'], True), (['ha', 'disabled'], True),
                                    (['matter', 'simulation'], False), (['replay'], False)):
            with self.subTest(providers=providers):
                response = MagicMock()
                response.__enter__.return_value = io.StringIO(json.dumps({
                    'mode': 'pilot', 'sensors': [{'provider': p} for p in providers]}))
                with patch.object(view_live.urllib.request, 'build_opener') as client:
                    client.return_value.open.return_value = response
                    if accepted:
                        self.assertTrue(view_live.dashboard_ready())
                    else:
                        with self.assertRaises(ValueError):
                            view_live.dashboard_ready()

    def test_new_tunnel_is_closed_on_interrupt(self):
        with patch.object(view_live.subprocess, 'run'), \
                patch.object(view_live, 'tunnel_listening', return_value=False), \
                patch.object(view_live.subprocess, 'Popen') as factory, \
                patch.object(view_live, 'dashboard_ready', side_effect=[False, True]), \
                patch.object(view_live.webbrowser, 'open', return_value=True):
            tunnel = factory.return_value
            tunnel.poll.return_value = None
            tunnel.wait.side_effect = [KeyboardInterrupt, 0]
            self.assertEqual(self.run_main(), 0)
            tunnel.terminate.assert_called_once()
            command = factory.call_args.args[0]
            self.assertIn('ExitOnForwardFailure=yes', command)
            self.assertIn('127.0.0.1:8840:127.0.0.1:8840', command)

    def test_ssh_failure_does_not_open_browser(self):
        with patch.object(view_live.subprocess, 'run', side_effect=subprocess.CalledProcessError(255, 'ssh')), \
                patch.object(view_live.webbrowser, 'open') as browser:
            self.assertEqual(self.run_main(), 1)
            browser.assert_not_called()

    def test_tunnel_failure_does_not_open_browser(self):
        with patch.object(view_live.subprocess, 'run'), \
                patch.object(view_live, 'tunnel_listening', return_value=False), \
                patch.object(view_live.subprocess, 'Popen') as factory, \
                patch.object(view_live, 'dashboard_ready', return_value=False), \
                patch.object(view_live.webbrowser, 'open') as browser:
            factory.return_value.poll.return_value = 255
            self.assertEqual(self.run_main(), 1)
            browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
