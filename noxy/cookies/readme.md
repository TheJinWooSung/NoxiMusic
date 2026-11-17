# YouTube Cookies

NoxiMusic reads YouTube cookie files from this directory.

## Local setup

1. Sign in to your own YouTube account in a desktop browser.
2. Use a trusted browser extension from the browser's official extension store to export cookies for YouTube only.
3. Select the Netscape `cookies.txt` format.
4. Save the exported file here as `cookies.txt`:

   `noxy/cookies/cookies.txt`

5. Restart NoxiMusic.

The file must be a Netscape-format text cookie jar, not a copied `Cookie:` request header. Do not edit cookie values manually.

## Configure a remote URL

Set `COOKIES_URL` in the environment to a private HTTPS URL serving the raw Netscape cookie file:

```env
COOKIES_URL=https://your-private-host.example/cookies.txt
```

Multiple URLs may be separated by commas or spaces. The first downloaded file is stored as `noxy/cookies/cookies.txt`; additional files are named `cookies-2.txt`, and so on.

For Docker, cookie files are excluded from the build context for security. Use `COOKIES_URL` or mount a persistent host directory at `/app/noxy/cookies` (already wired in `docker-compose.yml`).

## Security

- Cookie files can grant access to your signed-in session. Treat them like passwords.
- Never commit or publish cookie files, and never share a public URL containing them.
- Use HTTPS and a private, access-controlled host. Public pastes are not suitable for sensitive session cookies.
- Cookies expire. Export a fresh file from your own browser if YouTube rejects the existing file.
- Cookies are optional; without a valid file, NoxiMusic attempts public downloads without cookies.
