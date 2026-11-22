# MyFA: your finance advisor for WoW Forever

MyFA has two parts that work together:

- **MyFA** (in-game addon) scans the Auction House and records bags, bank, mailbox, gold and recipes on every character. It shows Buy / Items / Craft targets beside whichever Auction House window you use, tracks what you buy, and alerts you when a flip is worth selling.
- **MyFA Desk** (desktop app) turns those scans into flips, craft margins, raid prep, price charts and a dashboard, and writes the targets back into the addon.

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
