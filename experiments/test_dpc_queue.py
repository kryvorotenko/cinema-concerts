"""Run: python experiments/test_dpc_queue.py (no services required)."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('queueing', Path(__file__).resolve().parents[1] / 'dpc/api/app/queueing.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_capacity_cannot_be_taken_by_concurrent_request(self):
        queue = module.AdmissionQueue(1)
        with queue.reserve() as put:
            await asyncio.sleep(0)
            with self.assertRaises(asyncio.QueueFull):
                with queue.reserve():
                    pass
            put('scan-1')
        self.assertEqual(await queue.queue.get(), 'scan-1')

    async def test_failed_acceptance_releases_reservation(self):
        queue = module.AdmissionQueue(1)
        with self.assertRaises(RuntimeError):
            with queue.reserve():
                raise RuntimeError('database unavailable')
        with queue.reserve() as put:
            put('retry')
        self.assertEqual(queue.reserved, 0)

    async def test_empty_queue_suspends_worker_until_arrival(self):
        queue = module.AdmissionQueue(1)
        worker = asyncio.create_task(queue.queue.get())
        await asyncio.sleep(0)
        self.assertFalse(worker.done())
        with queue.reserve() as put:
            put('scan')
        self.assertEqual(await asyncio.wait_for(worker, 1), 'scan')


if __name__ == '__main__':
    unittest.main()
