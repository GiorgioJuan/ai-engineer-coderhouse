"""Verifica el limite de la corrida sin llamar al proveedor."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from scripts.servidor_presupuesto import BudgetTransport, LIMIT, MODEL, RESERVE


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "budget.json"
        self.sent = 0

        async def respond(request):
            self.sent += 1
            await asyncio.sleep(0)
            return httpx.Response(200, json={
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100}
            })

        self.transport = BudgetTransport(self.path, httpx.MockTransport(respond))
        self.client = httpx.AsyncClient(transport=self.transport)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.folder.cleanup()

    async def request(self):
        return await self.client.post("https://api.openai.com/v1/chat/completions",
                                      json={"model": MODEL, "max_tokens": 1024})

    async def test_concurrent_calls_settle_without_lost_updates(self):
        await asyncio.gather(*(self.request() for _ in range(5)))
        self.assertEqual(self.sent, 5)
        self.assertEqual(self.transport.data["charged_e8"], 5 * 21000)

    async def test_limit_blocks_before_send_and_survives_restart(self):
        self.transport.data["charged_e8"] = LIMIT - RESERVE + 1
        await self.transport.save()
        with self.assertRaisesRegex(RuntimeError, "Presupuesto agotado"):
            await self.request()
        self.assertEqual(self.sent, 0)
        restored = BudgetTransport(self.path, httpx.MockTransport(lambda r: None))
        self.assertEqual(restored.data["charged_e8"], LIMIT - RESERVE + 1)
        await restored.aclose()

    async def test_network_failure_keeps_full_reservation(self):
        async def fail(request):
            raise httpx.ReadTimeout("timeout", request=request)

        self.transport.inner = httpx.MockTransport(fail)
        with self.assertRaises(httpx.ReadTimeout):
            await self.request()
        self.assertEqual(self.transport.data["charged_e8"], RESERVE)
        self.assertEqual(self.transport.data["calls"][0]["status"], "reserved")

    async def test_windows_temporary_file_lock_is_retried(self):
        original = Path.replace
        attempts = 0

        def temporarily_locked(source, target):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise PermissionError("File being read")
            return original(source, target)

        with patch.object(Path, "replace", temporarily_locked):
            await self.request()
        self.assertEqual(self.sent, 1)
        self.assertEqual(self.transport.data["charged_e8"], 21000)


if __name__ == "__main__":
    unittest.main()
