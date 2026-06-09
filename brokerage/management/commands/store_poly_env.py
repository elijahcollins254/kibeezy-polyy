import os
from django.core.management.base import BaseCommand, CommandError

from brokerage.services.polymarket.auth import create_or_derive_api_key


class Command(BaseCommand):
    help = 'Store Polymarket L2 credentials in project .env (dev only). Do NOT commit .env to VCS.'

    def add_arguments(self, parser):
        parser.add_argument('--api-key', help='POLY_API_KEY')
        parser.add_argument('--api-secret', help='POLY_API_SECRET (base64)')
        parser.add_argument('--passphrase', help='POLY_API_PASSPHRASE')
        parser.add_argument('--address', help='POLY_ADDRESS (signer address)')
        parser.add_argument('--host', help='POLY_CLOB_BASE_URL or POLYMARKET_BASE_URL')
        parser.add_argument('--derive-from-private-key', action='store_true', help='Derive creds using POLY_PRIVATE_KEY (env or --host) via SDK')

    def handle(self, *args, **options):
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '..', '.env')
        # normalize path (the above may include ..)
        env_path = os.path.abspath(env_path)

        api_key = options.get('api_key')
        api_secret = options.get('api_secret')
        passphrase = options.get('passphrase')
        address = options.get('address')
        host = options.get('host')

        if options.get('derive_from_private_key'):
            # Attempt to derive using SDK helper
            try:
                creds = create_or_derive_api_key(host=host)
            except Exception as e:
                raise CommandError(f'Failed to derive creds: {e}')

            api_key = creds.get('apiKey')
            api_secret = creds.get('secret')
            passphrase = creds.get('passphrase')

        if not all([api_key, api_secret, passphrase, address]):
            raise CommandError('api_key, api_secret, passphrase, and address are required (provide via flags or use --derive-from-private-key and ensure POLY_PRIVATE_KEY is set)')

        # Read existing .env lines if present
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.read().splitlines()

        # Update or append values
        def set_var(key, value, arr):
            prefix = f"{key}="
            for i, l in enumerate(arr):
                if l.startswith(prefix):
                    arr[i] = prefix + value
                    return
            arr.append(prefix + value)

        set_var('POLYMARKET_API_KEY', api_key, lines)
        set_var('POLY_API_SECRET', api_secret, lines)
        set_var('POLY_API_PASSPHRASE', passphrase, lines)
        set_var('POLY_ADDRESS', address, lines)
        if host:
            set_var('POLY_CLOB_BASE_URL', host, lines)

        # Write back
        with open(env_path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

        self.stdout.write(self.style.SUCCESS(f'Wrote Polymarket credentials to {env_path} (do NOT commit to git)'))