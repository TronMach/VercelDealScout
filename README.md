# DealScout

Finds cheap prices for the games on a Steam wishlist or in a Steam library, using [GG.deals](https://gg.deals/api/).

- Sign in with Steam. DealScout never sees your Steam password.
- Each person adds their own API keys. They are checked, then stored encrypted on the server, and never shown again in full.
- Scan your wishlist, your library, or a friend's wishlist (Find Steam ID).
- Discord slash commands: `/link`, `/unlink`, `/wishlist`, `/library`.

## How it fits together

| Part | What it is |
| --- | --- |
| `client/` | React 19 + Vite + TanStack Query. Built to static files. |
| `server/server.py` | FastAPI. On Vercel it runs as one Python function (`api/index.py`); `vercel.json` sends every `/api/*` request to it. |
| `server/src/deals_service.py` | The wishlist and library scan. The web app and Discord both use it, so they show the same deals. |
| `server/src/auth.py` | Sign in with Steam (OpenID 2.0) and signed session cookies. |
| `server/src/db.py` | Users, encrypted keys, Discord links. SQLite locally, Postgres (Neon) on Vercel. Tables are created on first use. |
| `server/src/discord_app.py` | Discord's HTTP interactions endpoint (no always-on bot). |

Which keys a scan needs:

- **GG.deals API key**: every scan. Free at <https://gg.deals/api/>.
- **Steam Web API key**: My Library and Find Steam ID. Public wishlists work without one. Free at <https://steamcommunity.com/dev/apikey>.

GG.deals allows about 100 requests per window per key. A scan checks up to 450 games in batches of 30 (at most 15 requests). If GG.deals rate limits part of a scan, you get the deals found so far, with a note.

## Run it locally

You need Python 3.12 or newer and Node 20 or newer.

```bash
cd server
python -m venv .venv
.venv/Scripts/python -m pip install -r ../requirements-dev.txt
```

On macOS or Linux the venv path is `.venv/bin/python`.

Create `server/.env`. It's in `.gitignore`; never commit it.

```
SESSION_SECRET=<random text, at least 32 characters>
ENCRYPTION_KEY=<a Fernet key>
```

Make each value with:

```bash
.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Start the server (port 5000) and the client (port 5173), each in its own terminal:

```bash
.venv/Scripts/python server.py
```

```bash
npm --prefix client install
```

```bash
npm --prefix client run dev
```

Open <http://localhost:5173>. Vite forwards `/api` to the server. Locally the database is the file `server/dealscout.db`.

Run the tests:

```bash
cd server && .venv/Scripts/python -m pytest -q tests
```

### Environment variables

| Name | Where | What |
| --- | --- | --- |
| `SESSION_SECRET` | local + Vercel | Signs session cookies. Changing it signs everyone out. |
| `ENCRYPTION_KEY` | local + Vercel | Fernet key that encrypts stored API keys. **If you lose or change it, everyone has to enter their keys again.** |
| `DATABASE_URL` | Vercel | Postgres connection string. Added for you when you connect Neon. Leave it unset locally to use SQLite. |
| `APP_BASE_URL` | Vercel | The site's public address, for example `https://dealscout.vercel.app`. No trailing slash. |
| `DISCORD_PUBLIC_KEY` | Vercel | From the Discord Developer Portal. |
| `DISCORD_APP_ID`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` | your computer only | Used by `server/scripts/register_commands.py`. Vercel doesn't need them. |

## Deploy to Vercel

1. **Import the repo.** In Vercel, choose **Add New… > Project**, then import the GitHub repo. Leave **Root Directory** as the repo root. `vercel.json` sets the build (`client/dist`) and the Python function, so leave the build settings alone. Don't deploy yet if it offers; or let the first build fail, which is fine.
2. **Add the database.** In the project, open **Storage > Create Database > Neon (Serverless Postgres)**. Accept the free plan and connect it to the project for all environments. This adds `DATABASE_URL`.
3. **Add environment variables.** Open **Settings > Environment Variables** and add `SESSION_SECRET`, `ENCRYPTION_KEY` and `APP_BASE_URL`, for Production. Make new values for production; don't reuse your local ones.
4. **Deploy.** Open **Deployments**, then **Redeploy** the latest one so it picks up the variables.
5. **Check it.** Open the site, click **Sign in with Steam**, then add your keys on the Settings page and scan your wishlist.

Preview deployments (other branches) are behind Vercel's login by default, so Steam sign-in and Discord only work on the production address.

## Set up Discord

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and choose **New Application**. Name it DealScout.
2. On **General Information**, copy the **Public Key** into the Vercel variable `DISCORD_PUBLIC_KEY`, then redeploy.
3. On the same page, set **Interactions Endpoint URL** to `https://<your site>/api/discord/interactions` and save. Discord sends a test request; if saving fails, check that `DISCORD_PUBLIC_KEY` is set and the redeploy finished.
4. Copy the **Application ID** into `server/.env` as `DISCORD_APP_ID`.
5. On **Bot**, choose **Reset Token** and put the token in `server/.env` as `DISCORD_BOT_TOKEN`. Only the registration script uses it.
6. Optional, for testing: in Discord, turn on **Developer Mode** (User Settings > Advanced), right-click your server, choose **Copy Server ID**, and put it in `server/.env` as `DISCORD_GUILD_ID`. Commands then appear in that server at once instead of within an hour.
7. Register the commands:

   ```bash
   cd server && .venv/Scripts/python scripts/register_commands.py
   ```

8. Invite the app to your server. Replace `APP_ID` with your Application ID:

   `https://discord.com/oauth2/authorize?client_id=APP_ID&scope=applications.commands`

9. In Discord, type `/link`, open the link it sends you (only you can see it), and sign in with Steam. Then try `/wishlist`.

### Commands

| Command | What it does |
| --- | --- |
| `/link` | Sends you a private, single-use link (10 minutes) that connects your Discord account to your DealScout account. |
| `/unlink` | Disconnects it. |
| `/wishlist [steam] [max_price] [sort]` | Deals on your wishlist, or on someone else's if you give a profile link, custom name or SteamID64. |
| `/library [max_price] [sort]` | Deals on games in your library. Needs your Steam API key. |

Results show 10 deals per page with ◀ ▶ buttons. The buttons keep working for 7 days.

## Security notes

- Sessions are signed, HttpOnly, SameSite=Lax cookies (Secure on https).
- Requests that change data must come from the site itself (Origin check) and be JSON.
- Discord requests are checked against Discord's Ed25519 signature.
- API keys are encrypted with `ENCRYPTION_KEY`. The browser only ever gets the last 4 characters.
- Logs never include request URLs, because Steam and GG.deals take the key in the URL.
