"""Execute the shipped Lua daemon over TCP; fake only Kindle OS services."""
from __future__ import annotations

import ctypes.util
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from contextlib import contextmanager

from kindle_companion.pairing import _candidate, _stop_script, pairing_proof

ROOT = Path(__file__).resolve().parents[1]
DAEMON = ROOT / "assets/kindlepilot.koplugin/pairing_daemon.lua"
LUAJIT = shutil.which("luajit")
BOOTSTRAP = r'''
local ffi = require("ffi")
ffi.loadlib = function() return ffi.load(os.getenv("KINDLE_TEST_CRYPTO")) end
local core = os.getenv("KINDLE_TEST_LUASOCKET")
if core and core ~= "" then
    package.preload["socket.core"] = assert(package.loadlib(core, "luaopen_socket_core"))
    package.path = os.getenv("KINDLE_TEST_LUA_PATH") .. ";" .. package.path
end
local socket = require("socket")
local bind = socket.bind
socket.bind = function(_, port)
    local server, err = bind("127.0.0.1", port)
    if not server then return nil, err end
    return setmetatable({}, {__index = function(_, key)
        if key == "accept" then return function()
            local client = server:accept()
            if not client then return nil end
            return setmetatable({}, {__index = function(_, method)
                if method == "getpeername" then return function()
                    return "192.168.50.21", 40000
                end end
                return function(_, ...) return client[method](client, ...) end
            end})
        end end
        return function(_, ...) return server[key](server, ...) end
    end})
end
dofile(arg[1])
'''


@unittest.skipUnless(LUAJIT, "install LuaJIT and LuaSocket for daemon runtime tests")
class PairingDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = os.environ.copy()
        cls.env["KINDLE_TEST_CRYPTO"] = (
            cls.env.get("KINDLE_TEST_CRYPTO") or ctypes.util.find_library("crypto") or "crypto"
        )
        probe = BOOTSTRAP.split('local bind = socket.bind')[0]
        result = subprocess.run([LUAJIT, "-e", probe], env=cls.env, capture_output=True)
        if result.returncode:
            raise unittest.SkipTest("LuaSocket is missing; install lua-socket or set KINDLE_TEST_LUASOCKET")

    @contextmanager
    def device(self, duration=2, fail_dropbear=False, via_plugin=False, code="A1B2C3"):
        with tempfile.TemporaryDirectory(prefix="kindle-daemon-") as tmp:
            root = Path(tmp)
            base = root / "KindlePilot"
            base.mkdir()
            binary = root / "bin"
            binary.mkdir()
            (binary / "ip").write_text(
                '#!/bin/sh\ncase "$*" in\n'
                '*route*) echo "192.168.50.0/24 dev wlan0 scope link";;\n'
                '*) echo "    inet 192.168.50.82/24 scope global wlan0";;\nesac\n'
            )
            (binary / "iptables").write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$KINDLE_TEST_FIREWALL"\n'
            )
            (root / "dropbear").write_text(
                '#!/bin/sh\n'
                '[ -r settings/SSH/authorized_keys ] || exit 8\n'
                'pwd > "$KINDLE_TEST_CWD"\n'
                'printf "%s\\n" "$*" > "$KINDLE_TEST_ARGS"\n'
                + ("exit 9\n" if fail_dropbear else "exit 0\n")
            )
            for executable in [binary / "ip", binary / "iptables", root / "dropbear"]:
                executable.chmod(0o700)
            runtime = root / "runtime"
            runtime.mkdir()
            shutil.move(root / "dropbear", runtime / "dropbear")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            (base / "config.lua").write_text(
                "return { pairing_port=" + str(port)
                + ", ssh_port=2224, pairing_max_attempts=3, pairing_code_ttl_seconds=20,"
                + ' dropbear_path="' + str(runtime / "dropbear") + '",'
                + " session_duration_seconds=" + str(duration)
                + ', host_public_b64="' + "B" * 68 + '" }\n'
            )
            (base / "pairing.request.lua").write_text(
                'return {code="' + code + '", device_nonce="' + "d" * 32
                + '", expires_at=' + str(int(time.time()) + 20) + "}\n"
            )
            (base / "server_hostkey").write_bytes(b"fixture host identity")
            (base / "stop.sh").write_bytes(_stop_script(str(base), 2224, port))
            bootstrap = root / "bootstrap.lua"
            bootstrap.write_text(BOOTSTRAP)
            if via_plugin:
                plugin = root / "plugins/KindlePilot.koplugin"
                plugin.mkdir(parents=True)
                for name in ("pairing_daemon.lua", "pairing_daemon_entry.lua"):
                    shutil.copy(DAEMON.parent / name, plugin / name)
                (root / "luajit").symlink_to(LUAJIT)
                (root / "setupkoenv.lua").write_text(BOOTSTRAP.rsplit("dofile(arg[1])", 1)[0])
                bootstrap.write_text(r'''
local function noop() end
package.preload.datastorage = function() return {
    getFullDataDir=function() return arg[2] end
} end
package.preload["ui/widget/infomessage"] = function() return {new=function(_, value)
    print(value.text)
    return value
end} end
package.preload["ui/uimanager"] = function() return {
    show=noop, close=noop,
    scheduleIn=function(_, _, callback)
        os.execute("sleep 0.1")
        callback()
    end
} end
package.preload["ui/widget/container/widgetcontainer"] = function() return {
    extend=function(_, value) return value end
} end
package.preload.gettext = function() return function(value) return value end end
local plugin = dofile(arg[1])
plugin.ui = {menu={registerToMainMenu=noop}}
plugin:init()
plugin:start_pairing()
''')
            env = dict(self.env, PATH=str(binary) + os.pathsep + self.env["PATH"],
                       KINDLE_TEST_FIREWALL=str(root / "firewall"),
                       KINDLE_TEST_CWD=str(root / "cwd"),
                       KINDLE_TEST_ARGS=str(root / "dropbear-args"))
            with (root / "process.log").open("w+") as log:
                arguments = ([str(DAEMON.parent / "main.lua"), str(root)] if via_plugin
                             else [str(DAEMON), str(base), str(root)])
                process = subprocess.Popen(
                    [LUAJIT, str(bootstrap), *arguments],
                    env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
                try:
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        if (base / "status").exists() and "STATE=pairing" in (base / "status").read_text():
                            break
                        if process.poll() is not None:
                            log.seek(0)
                            self.fail("daemon exited before ready: " + log.read())
                        time.sleep(0.02)
                    else:
                        self.fail("daemon did not report ready")
                    yield root, base, port, process, env
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=4)

    def exchange(self, port, *, code="A1B2C3", fragments=False, proof_override=None):
        public = "A" * 68
        nonce = "a" * 32
        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.settimeout(5)
            stream = client.makefile("rb")
            hello = ("KINDLEPILOT/PAIR1 HELLO " + nonce + "\r\n").encode()
            if fragments:
                for start in range(0, len(hello), 7):
                    client.sendall(hello[start:start + 7])
                    time.sleep(0.005)
            else:
                client.sendall(hello)
            challenge = stream.readline().decode().split()
            self.assertEqual(challenge[:2], ["KINDLEPILOT/PAIR1", "CHALLENGE"])
            proof = proof_override or pairing_proof(code, nonce, public, challenge[2])
            client.sendall(f"KINDLEPILOT/PAIR1 AUTH {nonce} {public} {proof}\n".encode())
            return stream.readline().decode().split()

    def test_full_handshake_survives_probes_and_uses_isolated_authorized_keys(self):
        with self.device() as (root, base, port, process, _):
            for _ in range(4):
                with socket.create_connection(("127.0.0.1", port), timeout=3):
                    pass
            response = self.exchange(port, fragments=True)
            self.assertEqual(response[:2], ["KINDLEPILOT/PAIR1", "OK"])
            self.assertEqual(len(response), 6)
            self.assertEqual(response[3], "B" * 68)
            process.wait(timeout=4)
            self.assertEqual((root / "cwd").read_text().strip(), str(base))
            self.assertIn("-s -j -k", (root / "dropbear-args").read_text())
            self.assertEqual((base / "settings/SSH/authorized_keys").read_text(),
                             "ssh-ed25519 " + "A" * 68 + " kindlepilot-pair\n")
            self.assertFalse((root / "settings/SSH/authorized_keys").exists())
            self.assertEqual((base / "session.id").read_text().strip(), response[2])
            self.assertFalse((base / "pairing.request.lua").exists())

    def test_shipped_plugin_entry_starts_service_that_survives_gui_exit(self):
        with self.device(via_plugin=True) as (_, base, port, process, _):
            process.wait(timeout=4)
            self.assertEqual(process.returncode, 0)
            code = re.search(r'code = "([0-9]{6})"', (base / "pairing.request.lua").read_text())[1]
            self.assertEqual(self.exchange(port, code=code)[:2], ["KINDLEPILOT/PAIR1", "OK"])

    def test_host_client_pairs_with_shipped_daemon(self):
        with self.device(code="005219") as (root, _, port, process, _):
            identity = root / "client"
            identity.with_suffix(".pub").write_text("ssh-ed25519 " + "A" * 68 + "\n")
            result = _candidate("127.0.0.1", "127.0.0.1", "005219",
                                {"pairing_port": port, "host_public_b64": "B" * 68},
                                identity, strict=True)
            self.assertEqual(result["host_public_b64"], "B" * 68)
            self.assertEqual(result["port"], 2224)
            process.wait(timeout=4)

    def test_three_wrong_codes_revoke_pairing_without_authorizing_ssh(self):
        with self.device() as (root, base, port, process, _):
            for _ in range(3):
                self.assertEqual(self.exchange(port, code="FFFFFF")[:2],
                                 ["KINDLEPILOT/PAIR1", "ERROR"])
            process.wait(timeout=4)
            self.assertFalse((base / "settings/SSH/authorized_keys").exists())
            self.assertFalse((root / "cwd").exists())
            self.assertEqual((base / "status").read_text(), "STATE=stopped\n")

    def test_digest_differences_totaling_256_are_rejected(self):
        expected = pairing_proof("A1B2C3", "a" * 32, "A" * 68, "d" * 32)
        candidates = {0: ""}
        for char in expected:
            options = {}
            for total, prefix in candidates.items():
                for substitute in "0123456789abcdef":
                    distance = total + abs(ord(char) - ord(substitute))
                    if distance <= 256:
                        options[distance] = prefix + substitute
            candidates = options
        collision = candidates[256]
        self.assertNotEqual(collision, expected)
        with self.device() as (root, base, port, _, _):
            self.assertEqual(self.exchange(port, proof_override=collision)[:2],
                             ["KINDLEPILOT/PAIR1", "ERROR"])
            self.assertFalse((root / "cwd").exists())
            self.assertEqual(self.exchange(port)[:2], ["KINDLEPILOT/PAIR1", "OK"])

    def test_expiry_cleans_credentials_and_both_firewalls(self):
        with self.device(duration=1) as (root, base, port, process, _):
            self.assertEqual(self.exchange(port)[:2], ["KINDLEPILOT/PAIR1", "OK"])
            process.wait(timeout=4)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (base / "status").read_text() != "STATE=stopped\n":
                time.sleep(0.02)
            self.assertFalse((base / "session.id").exists())
            self.assertFalse((base / "settings/SSH/authorized_keys").exists())
            self.assertEqual((base / "status").read_text(), "STATE=stopped\n")
            rules = (root / "firewall").read_text()
            self.assertIn("-D INPUT -p tcp -s 192.168.50.21/32 --dport 2224", rules)
            self.assertIn("-D OUTPUT -p tcp -d 192.168.50.21/32 --sport 2224", rules)
            self.assertIn(f"-D OUTPUT -p tcp -d 192.168.50.0/24 --sport {port}", rules)

    def test_old_timer_preserves_a_newer_session(self):
        with self.device(duration=1) as (_, base, port, process, env):
            self.assertEqual(self.exchange(port)[:2], ["KINDLEPILOT/PAIR1", "OK"])
            process.wait(timeout=4)
            (base / "session.id").write_text("newer-session\n")
            time.sleep(1.2)
            self.assertTrue((base / "settings/SSH/authorized_keys").exists())
            subprocess.run(["sh", str(base / "stop.sh")], check=True, env=env, capture_output=True)
            self.assertFalse((base / "settings/SSH/authorized_keys").exists())

    def test_dropbear_failure_returns_a_diagnostic(self):
        with self.device(fail_dropbear=True) as (_, base, port, _, _):
            self.assertEqual(self.exchange(port), ["KINDLEPILOT/PAIR1", "ERROR", "SSH_START_FAILED"])
            self.assertFalse((base / "settings/SSH/authorized_keys").exists())


if __name__ == "__main__":
    unittest.main()
