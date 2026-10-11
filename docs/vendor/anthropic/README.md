Anthropic TypeScript SDK `@anthropic-ai/sdk@0.127.0` (MIT), as bundled by jsDelivr (`/+esm`), saved as `.js` so
any web server sends it as JavaScript. Its imports (`standardwebhooks@1.1.1`, `@stablelib/base64@1.0.1`,
`fast-sha256@1.3.0` and the SDK's two `node.browser` stubs) point at the local copies here, so the AI builder
works the same in the desktop app and on the website without loading anything else.
