# MyFA: your finance advisor for WoW Forever

MyFA has two parts that work together:

- **MyFA** (in-game addon) scans the Auction House and records bags, bank, mailbox, gold and recipes on every character. It shows Buy / Sell / Craft / My flips tabs beside whichever Auction House window you use, tracks what you buy and sell (from your Auction House mail), and alerts you when a flip is worth selling.
- **MyFA Desk** (desktop app) turns those scans into flips, craft margins, raid prep, neutral Auction House trades, real profit from your sales, price charts and a dashboard, and writes the targets back into the addon.

Nothing is automated: every purchase in game is your click.

## Install

1. Download `MyFA-Kit-vX.Y.Z.zip` from the [latest release](https://github.com/niranjraj/MyFa/releases/latest).
2. Copy the `MyFA` folder into `World of Warcraft\_forever_\Interface\AddOns\`.
3. Put `MyFA-Desk` anywhere (Documents is fine). Install Python 3.9+ from python.org, ticking **Add python.exe to PATH**.
4. Double-click **`MyFA-Desk\MyFA Desk.pyw`**. It runs in the background with no terminal and opens your dashboard in the browser. Use **Settings > Add MyFA to desktop** for a desktop icon.

The full guide is in [MyFA-Desk/README.md](MyFA-Desk/README.md).

## Updates

MyFA Desk checks this repo's releases when it starts and every few hours. The **Check for updates** button in the dashboard's top bar turns gold when a new version is out. When a new version is out, it asks, then updates both the Desk app and the addon in your `_forever_` folder. Your settings, price history and any edits to `raids.json` are kept. Type `/reload` in game afterwards.

- Click **Check for updates** to check right now (or `run_desk.bat --update` in a terminal).
- Set `"auto_update"` in `config.json` to `"always"` (no prompt) or `"never"`.
- Addon managers that install from a GitHub URL can use the `MyFA-vX.Y.Z.zip` asset of each release.

## Releasing a new version (maintainer)

1. Make the changes and add a `## X.Y.Z` section to `CHANGELOG.md`.
2. Put the new number in `MyFA-Desk/VERSION` (for example `1.0.1`).
3. Commit and push to `main`.

The **Release** workflow sees the new version, checks the Lua and Python, stamps the version into the addon, builds the three zips and publishes release `vX.Y.Z`. Everyone's Desk picks it up on its next start. Pushing a `vX.Y.Z` tag, or running the workflow by hand from the Actions tab, also works.

## Playing within Blizzard's rules

MyFA is built so that nothing it does could count as automation:

- **Every buy, post and cancel is your click.**
  - **Buy** and **Confirm** are two separate clicks.
  - Posting is always your click on Blizzard's own **Post** button. MyFA only fills in the price, quantity and duration, which is the same as typing them yourself.
  - **Cancel** cancels one auction per click.
  - The game itself enforces this: these actions only work from a real click.
- **Scans and price checks are ordinary Auction House reads.**
  - A full scan runs at most once every 15 minutes, as Blizzard allows.
  - **Check prices** sends one search at a time with a pause between them, only when you press it, and stops when the Auction House closes.
- **No messages to other players, no macros, no key presses sent to the game.** Alerts are only shown to you.
- **MyFA Desk never touches the game.** It reads the file WoW saves when you /reload and writes a data file the addon loads. That's the same way the TSM desktop app works.
- **The addon follows Blizzard's add-on policy:** it is free, the code is fully readable, and it has no ads or donation requests.

No tool can promise how Blizzard will judge every case, but MyFA stays inside the limits the game itself enforces on addons. Those are the same limits Auctionator and TradeSkillMaster work within.

## CurseForge

The in-game addon goes on CurseForge. **MyFA Desk** stays on GitHub Releases (the latest one is always at https://github.com/niranjraj/MyFa/releases/latest); link it from the CurseForge description. That's how TSM ships its desktop app.

### One-time setup (maintainer)

1. **Get an API token:** at https://legacy.curseforge.com/account/api-tokens, create a token named, say, `github`.
2. **Note your Project ID:** it's in the **About Project** box on your CurseForge project page.
3. **Add both to GitHub:** in this repo, open **Settings > Secrets and variables > Actions**.
   - **Secrets** tab: add `CF_API_TOKEN` with the token.
   - **Variables** tab: add `CF_PROJECT_ID` with the project ID.
4. **Upload the current version:** go to **Actions > Upload to CurseForge > Run workflow**. After that, every new release uploads on its own.
5. **If the upload says it can't find the WoW Forever game version:** add a variable `CF_GAME_VERSIONS` with the version name CurseForge shows for Forever (the error lists the options), then run it again.

CurseForge reviews a project's first file before it shows in the CurseForge app.

### For players
- Install **MyFA** from CurseForge (pick your Forever installation in the CurseForge app).
- Download **MyFA Desk** from GitHub Releases and start it.
- Desk sees that the addon came from CurseForge and leaves addon updates to the CurseForge app. It updates only itself. Settings > **In-game addon updated by** changes this.
- Keep the small **MyFA Desk data** addon enabled in the AddOns list. Desk creates it; it holds your targets.
