# MyFA: your finance advisor for WoW Forever

MyFA has two parts that work together:

- **MyFA** (in-game addon) scans the Auction House and records your bags, bank, gold and recipes. It shows Buy / Items / Craft targets beside the Auction House.
- **MyFA Desk** (desktop app) turns those scans into flips, craft margins, raid prep, price charts and a dashboard, and writes the targets back into the addon.

Nothing is automated: every purchase in game is your click.

## Install

1. Download `MyFA-Kit-vX.Y.Z.zip` from the [latest release](https://github.com/niranjraj/MyFa/releases/latest).
2. Copy the `MyFA` folder into `World of Warcraft\_forever_\Interface\AddOns\`.
3. Put `MyFA-Desk` anywhere (Documents is fine). Install Python 3.9+ from python.org, ticking **Add python.exe to PATH**.
4. Double-click `MyFA-Desk\run_desk.bat` and leave it open while you play.

The full guide is in [MyFA-Desk/README.md](MyFA-Desk/README.md).

## Updates

MyFA Desk checks this repo's releases each time it starts. When a new version is out, it asks, then updates both the Desk app and the addon in your `_forever_` folder. Your settings, price history and any edits to `raids.json` are kept. Type `/reload` in game afterwards.

- Run `run_desk.bat --update` to check right now.
- Set `"auto_update"` in `config.json` to `"always"` (no prompt) or `"never"`.
- Addon managers that install from a GitHub URL can use the `MyFA-vX.Y.Z.zip` asset of each release.

## Releasing a new version (maintainer)

1. Update `CHANGELOG.md` with a `## X.Y.Z` section.
2. Commit, then tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The **Release** workflow checks the Lua and Python, stamps the version, builds the three zips and publishes the release. Everyone's Desk picks it up on its next start.
