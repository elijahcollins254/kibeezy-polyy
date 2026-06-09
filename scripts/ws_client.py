#!/usr/bin/env python3
"""
Simple WebSocket client that:
 - logs in with phone+password to obtain session cookie
 - requests a JWT via POST /api/auth/token/
 - connects to the market websocket using ?token=<jwt>

Usage:
    python3 scripts/ws_client.py --host http://localhost:8000 --phone +2547XXXX --password secret --market 1

Requires: requests, websockets
"""
import argparse
import asyncio
import json
import logging
import sys

import requests
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='http://localhost:8000')
    p.add_argument('--phone', required=True)
    p.add_argument('--password', required=True)
    p.add_argument('--market', default='1')
    return p.parse_args()


async def run(host, phone, password, market_id):
    session = requests.Session()
    login_url = f"{host}/api/auth/login/"
    token_url = f"{host}/api/auth/token/"

    logger.info('Logging in...')
    resp = session.post(login_url, json={'phone_number': phone, 'password': password})
    if resp.status_code != 200:
        logger.error('Login failed: %s %s', resp.status_code, resp.text)
        sys.exit(1)

    logger.info('Requesting JWT token...')
    resp = session.post(token_url)
    if resp.status_code != 200:
        logger.error('Token request failed: %s %s', resp.status_code, resp.text)
        sys.exit(1)

    token = resp.json().get('token')
    if not token:
        logger.error('No token in response: %s', resp.text)
        sys.exit(1)

    ws_url = host.replace('http', 'ws').rstrip('/') + f"/ws/markets/{market_id}/?token={token}"
    logger.info('Connecting to %s', ws_url)

    async with websockets.connect(ws_url) as ws:
        logger.info('Connected, waiting for messages (5s)')
        try:
            # wait for messages for a short time
            end_time = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < end_time:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    logger.info('recv: %s', msg)
                except asyncio.TimeoutError:
                    # no message in window
                    continue
        except websockets.ConnectionClosed as e:
            logger.info('Connection closed: %s', e)


if __name__ == '__main__':
    args = parse_args()
    asyncio.run(run(args.host, args.phone, args.password, args.market))
