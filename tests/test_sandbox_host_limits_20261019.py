"""The plugin sandbox must not put resource limits on the host process (2026-10-19).

It used to set RLIMIT_AS and RLIMIT_CPU on the process running the plugin, which is the server itself. A lowered hard
limit can't be raised back without privilege, so the first plugin call capped the server's memory for good. And a
CPU limit below the CPU the server had already used got the server SIGKILLed. That's also why the whole suite, run
in one process, died at test_plugins' first execute.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _run(code):
    """In a child, so a sandbox that limits its own process can't take the test runner down with it."""
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=60,
                          cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO)})


@pytest.mark.parametrize("method, expect", [("handle", 4), ("ahandle", 6)])
def test_execute_leaves_the_hosts_limits_alone(method, expect):
    proc = _run(f'''
        import asyncio, json, resource
        from kintsugi.plugins.loader import LoadedPlugin, PluginMetadata, PluginState
        from kintsugi.plugins.sandbox import PluginSandbox, SandboxPolicy
        class P:
            def handle(self, x):
                return x * 2
            async def ahandle(self, x):
                return x * 3
        lims = (resource.RLIMIT_AS, resource.RLIMIT_CPU)
        before = [resource.getrlimit(l) for l in lims]
        plugin = LoadedPlugin(metadata=PluginMetadata(name="p", version="1.0.0", author="t", description="d"),
                              module=None, state=PluginState.LOADED, instance=P())
        r = asyncio.run(PluginSandbox(SandboxPolicy(max_memory_mb=64, max_cpu_seconds=1)).execute(plugin, "{method}", 2))
        print(json.dumps({{"result": r.result, "error": r.error, "before": before,
                          "after": [resource.getrlimit(l) for l in lims]}}))
    ''')
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-500:])
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["result"] == expect, out["error"]
    assert out["after"] == out["before"], out


def test_a_server_that_has_used_more_cpu_than_the_limit_survives_a_plugin_call():
    code = '''
        import asyncio, time
        from kintsugi.plugins.loader import LoadedPlugin, PluginMetadata, PluginState
        from kintsugi.plugins.sandbox import PluginSandbox, SandboxPolicy
        class P:
            def handle(self):
                return "ok"
        t = time.process_time()
        while time.process_time() - t < 1.5:          # the server has used 1.5 s of CPU
            pass
        plugin = LoadedPlugin(metadata=PluginMetadata(name="p", version="1.0.0", author="t", description="d"),
                              module=None, state=PluginState.LOADED, instance=P())
        r = asyncio.run(PluginSandbox(SandboxPolicy(max_cpu_seconds=1)).execute(plugin, "handle"))
        t = time.process_time()
        while time.process_time() - t < 0.5:          # and keeps working afterwards
            pass
        print("alive", r.result)
    '''
    proc = _run(code)
    assert proc.returncode == 0 and "alive ok" in proc.stdout, (proc.returncode, proc.stderr[-500:])
