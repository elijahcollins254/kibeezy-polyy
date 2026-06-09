WebSocket JWT example

1) Obtain a JWT: (after logging in via `POST /api/auth/login/` with session)

curl -X POST -c cookies.txt -H "Content-Type: application/json" -d '{"phone_number":"+2547xxxx","password":"secret"}' http://localhost:8000/api/auth/login/

# Then request token using cookie session
curl -X POST -b cookies.txt http://localhost:8000/api/auth/token/

Response: {"token":"<JWT_TOKEN>"}

2) Connect with querystring:

javascript
const token = '<JWT_TOKEN>'
const ws = new WebSocket(`ws://localhost:8000/ws/markets/123/?token=${token}`)

ws.onopen = () => console.log('connected')
ws.onmessage = (e) => console.log('msg', e.data)

3) Or connect with Authorization header (browser WebSocket doesn't allow custom headers;
   use wss + server proxy or use querystring in browsers). For server-to-server, include header:

# Example with Node ws library
const WebSocket = require('ws')
const ws = new WebSocket('ws://localhost:8000/ws/markets/123/', {
  headers: { 'Authorization': `Bearer ${token}` }
})

ws.on('open', () => console.log('connected'))
ws.on('message', (msg) => console.log(msg))
