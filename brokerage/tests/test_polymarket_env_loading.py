import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from brokerage.services.polymarket import client as polymarket_client


class PolymarketEnvLoadingTests(SimpleTestCase):
    def test_resolve_setting_reads_dotenv_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / '.env'
            env_path.write_text('POLY_PRIVATE_KEY=0xabc123\nPOLY_ADDRESS=0xdef456\n', encoding='utf-8')
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                self.assertEqual(polymarket_client._read_env_setting('POLY_PRIVATE_KEY'), '0xabc123')
                self.assertEqual(polymarket_client._read_env_setting('POLY_ADDRESS'), '0xdef456')
            finally:
                os.chdir(cwd)
