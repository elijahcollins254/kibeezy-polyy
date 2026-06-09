from django.core.management.base import BaseCommand
import os
import json
from brokerage.services.polymarket.auth import create_or_derive_api_key


class Command(BaseCommand):
    help = 'Create or derive Polymarket API credentials using L1 private key (requires py_clob_client_v2)'

    def add_arguments(self, parser):
        parser.add_argument('--private-key', help='Private key (hex) to use for L1 signing. If omitted, reads POLY_PRIVATE_KEY env var.')
        parser.add_argument('--host', help='Polymarket CLOB host (optional)')

    def handle(self, *args, **options):
        private_key = options.get('private_key') or os.getenv('POLY_PRIVATE_KEY')
        host = options.get('host') or os.getenv('POLYMARKET_BASE_URL')

        if not private_key:
            self.stderr.write('Private key is required (set POLY_PRIVATE_KEY or pass --private-key)')
            return

        try:
            creds = create_or_derive_api_key(private_key=private_key, host=host)
            self.stdout.write(json.dumps(creds, indent=2))
        except Exception as e:
            self.stderr.write(f'Error creating/deriving API credentials: {e}')
