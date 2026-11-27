# MyFA: auction house profit kit for WoW Forever

Two parts that pass data through files, the same way TradeSkillMaster's desktop app does:

- **MyFA** (in-game addon) runs a full Auction House scan and records your **bags, bank** (and warband bank if Forever has one), gold, the recipes you know in **every profession**, and vendor prices you see. It also shows a **Buy / Sell / Craft / My flips** panel beside the Auction House, with Search and Buy buttons and price lines in item tooltips.
- **MyFA Desk** (desktop app) watches the scan data. Each time you `/reload` it updates its price history, finds flips, vendor flips and craft margins, works out the best use of everything you own, charts price history, writes the targets back into the addon, and refreshes `report.html`.

Nothing is automated. Every purchase is your click, and WoW itself requires that.

## Install (once)

1. **Addon:** copy the `MyFA` folder to
   `World of Warcraft\_forever_\Interface\AddOns\MyFA`
   (the `.toc` file must sit directly inside `AddOns\MyFA`). Enable it at the character screen.
2. **Python:** install Python 3.9 or newer from python.org and tick **Add python.exe to PATH**. The app uses only the standard library, so there's nothing else to install.
3. **Desk:** put the `MyFA-Desk` folder anywhere (Documents is fine) and double-click **`MyFA Desk.pyw`**. No terminal opens: Desk runs quietly in the background and opens your dashboard in the browser at `http://127.0.0.1:47800`. If it can't find your `_forever_` folder, the page shows **Setup needed**: open **Settings**, press **Find it** or paste the folder (Battle.net, gear next to Play, **Show in Explorer**), then **Save**.
4. In **Settings**, press **Add MyFA to desktop** for a desktop icon you can double-click next time.

Prefer a terminal? `run_desk.bat` still works the same as before.

## The loop

1. Start **MyFA Desk** (double-click) and leave it running. The bar at the top of the dashboard shows **Watching** with a pulsing green dot.
2. In game, open the Auction House. The MyFA panel docks to its right. Press **Full scan**.
   Blizzard allows one full scan every 15 minutes; the button counts down.
3. Type `/reload`. WoW saves the scan, Desk reads it within about 2 seconds, and the dashboard shows **New scan ready, refresh**.
4. Type `/reload` again. The panel now has your targets.
5. **Buy:** press Buy. The addon asks the server for the live price and only offers **Confirm** if it's at or under the max. Press Confirm to buy.
   Gear only has **Search**, which jumps the Auction House to the item.
6. **Once per character:** open each profession window (Alchemy, Tailoring, Cooking, anything) so MyFA learns your recipes, and open your **bank** so it can count what's in it. MyFA re-reads the bank each time you visit. Visiting the vendor who sells vials and thread teaches it their prices.

`/myfa` toggles the panel, `/myfa scan` scans, and `/myfa status` shows data age.

## The in-game panel

At the top: when you last scanned, how old your targets are, and when the next scan is allowed. Under that, either the **scan progress bar** or a **Next:** line that always says what to do now. The line under the tabs explains each tab, every row has a coloured label (FLIP, VENDOR, RAID, SELL, CRAFT, KEEP, SELL NOW, HOLD...), and hovering a row gives step-by-step instructions.

**Scanning:** press **Full scan** and keep the Auction House open. The bar shows "Asking the server..." with a seconds counter (the server doesn't report progress for this part), then "Reading auctions 45% (12,300 of 27,400)", then "Done". Closing the MyFA panel doesn't stop a scan. Closing the Auction House does, with a message, and so does a server that hasn't answered after 2 minutes. Just press Full scan again.

The right-hand number means something different on each tab.

| Tab | What it shows | The right-hand number |
|---|---|---|
| **Buy** | Cheap listings worth buying to resell, vendor flips and raid stock-ups. Each row says how many to buy and the most to pay each. **Search** jumps the Auction House to the item. **Buy** checks the live price, then **Confirm** buys. | Your profit after reselling, with the cut taken off |
| **Sell** | Everything you own on all characters, with the best thing to do: post (at a price, each), sell to a vendor, craft into something, or keep for raid week or a rising price. Where it is shows on the right of each row. | What the whole stack is worth that way |
| **Craft** | Recipes you know that make a profit, with mat cost and sale price. | Profit per craft |
| **My flips** | What you bought and still hold, with what you paid and whether to sell yet. | Profit if you sold now |

Items with fewer than 10 listed (often recipes and patterns) are thin markets. They can look very profitable but may take weeks to sell, so they stay off the Buy tab and show as high-risk snipes at the bottom of Desk's Flips tab. Set `"include_snipes": true` in `config.json` to see them in game too.

## Flip tracking and sell alerts

- **Automatic tracking:** every Auction House purchase is recorded, whether you buy through the MyFA panel, the Blizzard window or another addon. As a backup, opening your mailbox reads your "Auction won" mails and records anything that was missed. Items still waiting in the mailbox show as "on its way, mail". For something you bought before installing MyFA, shift-click it into `/myfa bought [item] qty price`, for example `/myfa bought [Golden Sansam] 20 14s50c`.
- **Alerts:** when the lowest listing clears your profit target, you get a raid-warning message, a sound and a chat line naming the character and bag, bank or mailbox that holds it. The default target is 15% after the cut; change it with `/myfa roi 20`. Checks run after every scan, when you open the Auction House and when you log in. Repeats come at most every 12 hours, or sooner if the price climbs another 10%.
- **Desk:** prints the same alert and shows a Windows notification. Turn that off with `"desktop_notifications": false`.
- **Raid items:** if the item is also a raid consumable, the alert says so, because launch week usually pays more and you may want to hold.
- **Where to see them:** the **My flips** tab in game and **My flips** in Desk list what you paid, the price now, the alert price, the profit now and a note.
- **Add flips by hand:** press **+ Add flip** on the My flips tab in game (or `/myfa add`), drop the item in or shift-click it, then enter quantity and price each. In MyFA Desk, use the **Add a flip** form on My flips. It suggests item names, and the flip reaches the game on your next /reload.
- **Stop tracking** a flip with **Remove** on its row in Desk, or `/myfa forget [item]` in game. Turn alerts off with `/myfa alerts off`.

## Gear upgrades

**To get your upgrades:**
1. Log in on each character once, so the addon notes what it wears.
2. Press **Full scan** at the Auction House. The addon reads the stats of every gear listing in the background, and chat says when it's done.
3. Type `/reload`. Desk's **Gear upgrades** tab then lists the upgrades.

**For each character** you pick the class, main spec and off spec, and tick **PvP** if Stamina should count for more. Then press **Save and recalculate**.
- Each item gets a score from its stats and the spec's stat weights.
- An upgrade scores higher than what you wear in that slot. Rings and trinkets are compared with your weaker one; a two-hander with your main hand and off hand together.
- Only gear your class and level can use is listed.
- On-use and proc effects aren't counted.
- Sort by **Upgrade per gold** to find cheap big jumps.

**Stat weights:** Desk writes them to `data/stat_weights.json` the first time. Change any number there; class and spec names must stay as they are.

**In game:** the **Gear** tab shows the same lists for the character you're on. The button at the bottom switches between main and off spec.

## Booty Bay Broker deals

[Booty Bay Broker](https://bootybaybroker.com/forever/deals) tracks WoW Forever prices hourly and estimates how many of each item sell a day. To check their deals with MyFA's flip rules:

1. Open their WoW Forever deals page and pick your region, realm and faction.
2. Press **Ctrl+A**, then **Ctrl+C**.
3. In Desk's **Flips** tab, paste into **Check Booty Bay Broker deals** and press **Check deals**. Paste more pages the same way.

What MyFA does with them:
- **Checks every deal:**
  - is there a gap to the next listing (you must be the cheapest seller after buying);
  - does it sell at least `min_sold_per_day` a day by their estimate;
  - is there a supply surge;
  - does it clear your profit after the cut.
- Deals that pass join your flips and the in-game Buy list. The summary line says why the others failed.
- If your own scan is newer than theirs, your scan wins.
- Pasted deals expire after 6 hours.

MyFA never fetches their site itself: their terms forbid automated scraping, so this is always a copy and paste you do.

## Posting and undercuts

- **Sell tab:** each item to post shows MyFA's plan (price, quantity, duration). Press **Post** at the Auction House and MyFA fills in Blizzard's sell window; check it and press **Post** there.
  - The price matches the cheapest other seller.
  - It never goes below your floor: what you paid plus the cut and likely lost deposits, or the vendor price.
  - Quantity is capped at about half of what's listed.
  - Duration is the longest one whose deposit is worth risking for how often the item sells for you.
  - A red SELL tag means the deposit is high for something that rarely sells.
- **If you post through another addon's window** (The Market, say), the plan is also printed in chat: type those numbers there.
- **Listed tab:** your auctions here, each with how long it's been up (back through relists), how many relists, and time left. Each one is marked:
  - **UNDERCUT** (with a repost price);
  - **PRICE FELL** (the market dropped under what you paid; your price won't sell);
  - **CHEAP DUMP** (a few cheap units; most still sell above your floor);
  - **TOO HIGH**;
  - **LOWEST**.
  Hover a row for what to do. Desk shows the same on My flips under **Your auctions**.
  - **Check prices** looks up live prices, one search at a time.
  - **Cancel** cancels one auction per click. The deposit is lost and the items come back by mail; then post them again from the Sell tab.

## Profit from your sales

- When an auction sells, expires or is cancelled, open a mailbox on that character. MyFA reads the mail, closes the flip it belongs to with the real profit, and records any deposit you lost. Type `/reload` and Desk's **Profit** tab shows:
  - what flips, raid holds, crafts and farmed or looted items made (7 days, 30 days, all time);
  - profit by day;
  - how each item sells;
  - items that keep coming back unsold;
  - every sale and lost deposit.
- In game, `/myfa profit` prints the 7-day and 30-day totals.
- **Deposit risk:** MyFA learns how often each item sells for you and what your deposits are. Every profit figure (flips, crafts, sell suggestions, alert prices) already subtracts the deposits you'd lose relisting the unsold part. Until it has your own sales, it assumes 60% of listings sell (`default_sell_rate`).

## Neutral Auction House

- Gadgetzan, Booty Bay and Everlook share one neutral market with the Alliance. It takes a 15% cut and charges about five times the deposit.
- Scan there like anywhere else. MyFA recognises it, keeps those prices separate, and says so in chat. If it guesses wrong, type `/myfa ah neutral` or `/myfa ah faction` (and `/myfa ah auto` to go back).
- Desk's **Neutral AH** tab lists:
  - what to buy there and sell at home;
  - what to buy at home and sell there;
  - what you own that fetches more there.
- In game, the Buy and Sell tabs switch to the neutral lists while you stand at a neutral Auction House. Neutral prices older than a week are ignored.

## Guide

The **Guide** tab in MyFA Desk answers "what should I do next?":

- **Your characters:** level, class, zone, profession skills and gold for each character. Log in once on each, and open each profession window once.
- **Your next moves:** up to ten concrete actions ranked by gold: sell what's ready, post your items, craft from what you own, buy the best flips, what your gathering skill can pick that sells best now, and when to visit a trainer.
- **Researched guide:** Claude searches Wowhead and current WoW Forever guides for your characters and writes a plan: quests that pay at your level, profession next steps priced from your own scans, farms, items about to move and recent Forever changes, with sources. Refresh it when you level up or a patch lands. Three ways to run it (**Settings > Guide uses**; Automatic picks for you):
  - **Claude Code, your Claude plan, one click.** Install Claude Code (claude.com/claude-code), open a terminal, run `claude` once and log in with your Claude account. Then **Fetch guide** runs it in the background. It takes a few minutes and counts against your plan's usage, not API credit.
  - **Claude chat, your Claude plan, no install.** **Copy request**, then **Open Claude**, paste it and send (with web search on). Copy Claude's reply into the box and press **Save to Guide**.
  - **Claude API key, API credit.** Paste a key from console.anthropic.com in Settings. A fetch uses up to 8 web searches and costs a few cents.

  In the terminal, `run_desk.bat --guide` uses Claude Code or the API key, or writes `claude_guide_request.md` for you to paste into Claude chat.

Gathering skill requirements use classic values; Forever's new herbs and any changed nodes aren't in that list yet.

## Multiple characters

Log in once on each character with MyFA enabled and open its bank and mailbox once. MyFA combines bags, bank and mailbox across every character on the same Auction House (same ruleset and faction). The panel, tooltips and Desk all show where each item is, for example *Mooreth bank 9, Zelrin bags 5*. Gold is totalled across characters too. Auction House purchases land in the mailbox first, so they count before you collect them.

## Panel position

The panel docks to the right of whichever Auction House window is open, including other addons' windows. If there's no room on the right, it docks on the left. Drag it anywhere and it stays there; `/myfa dock` snaps it back. `/myfa help` lists every command.

## Reading the results

- **Analysis** (opens first) is your overview:
  - **Raid prep:** counts down to the next raids in `raids.json` (Barrow Deeps, Hyjal Summit and Onyxia's Lair on 9 Dec 2026) and shows where you are in the cycle: Stock up, Build stock, Launch week, Raiding, Settled. For each flask, elixir, potion, food, weapon buff and raid mat on the Auction House, it gives an action: **Buy** (at or under its usual low, with a quantity), **Craft & hold**, **Hold**, **Wait for dip**, **Sell** (launch week onward) or **Don't buy** (prices at their peak). Raid buys also show up in the in-game Buy tab as *raid stock*, and raid items in your bags or bank are marked *hold for raid launch* until launch week.
  - **Market movement:** a price index for all items, herbs, consumables, and cloth and leather (100 = price at first scan), plus the biggest risers and fallers this week.
  - **Flip bands:** items that swing within a range rather than trending. *Buy under* is their usual low and *sell at* their usual high, with the profit per unit after the cut. Items currently in the buy zone are listed first.
  - **Best day to buy and sell:** which weekday prices are lowest and highest. It needs 14 days of scans.
  - **How to flip on Forever:** the playbook, using your current numbers.
- **Flips:** units listed under 70% of market. For the first 3 days, before there's history, they come only from price gaps inside one scan. After that they use the median of up to 14 days. Profit includes the Auction House cut, quantity is capped at 35% of an item's supply and 30% of your gold, and items whose price is falling are marked high risk.
- **Vendor flips:** listed below what a merchant pays. These carry no risk.
- **Bags & bank:** everything you own on this realm, combined, with the best thing to do with each item:
  - **Auction House:** post at today's lowest price.
  - **Vendor:** a merchant pays more than the Auction House would.
  - **Craft:** worth more turned into one of your recipes, with the recipe named.
  - **Hold:** the price has been rising 4% or more a day, so selling later may pay more.

  *Gain vs next* shows how much better the best use is than the runner-up.
- **Crafts:** every recipe from every profession you've opened. Each shows the profit buying mats today, how many you can **make from stock** with only what's in your bags and bank, and the gain over selling those mats raw.
- **Gathering:** herbs, ore, leather, cloth, cooking and elemental mats ranked by market value, with their 7-day change. Use it to decide what to farm.
- **Trends:** a price-history chart (market and lowest listing, plus quantity listed) for every item you've scanned on 2 or more days. Click any item name in any tab to chart it, hover for exact daily values, and switch between 14, 30 and 60 days. The table ranks items by average daily change, so rising prices are at the top.
- **Activity:** what you bought through the panel.

Market value is set by where the bulk of supply sits, not by the cheapest listing, so one person dumping cheap stock doesn't drag it down.

## Settings (`config.json`, created on first run)

| Key | Default | Meaning |
|---|---|---|
| `ah_cut` | 0.05 | Blizzard hasn't published Forever's cut. Read a sale mail and set the real number. |
| `min_profit` | 5000 | Minimum profit per flip target, in copper (5000 = 50s). |
| `min_roi` | 0.15 | Minimum return after the cut. |
| `flip_threshold` | 0.7 | Buy under this fraction of market. |
| `max_supply_share` | 0.35 | Most of an item's listed supply you'll buy. |
| `max_spend_fraction` | 0.3 | Most of your gold to put into one item. |
| `include_gear` | false | Gear with random suffixes ("of the Bear") shares one item ID, so its prices are mixed. Leave this off unless you know the item. |
| `vendor_costs` | {} | `{"3371": 4}` sets the price of a vendor mat MyFA hasn't seen yet. |
| `band_days` | 30 | Days of history behind buy-under / sell-at bands. |
| `min_band_spread` | 0.2 | Only show bands with at least 20% profit after the cut. |
| `realm` | "" | Pin a ruleset and faction such as `Normal-Horde`. Blank uses the latest scan. |
| `history_days` | 14 | Days of prices that set market value. |
| `chart_days` | 60 | Days of history kept in the Trends charts. |
| `hold_rising_slope` | 0.04 | Suggest holding an item instead of selling once it's rising this fast per day. |
| `min_sold_per_day` | 1.0 | Flips only for items that sell at least this many a day on that Auction House. |
| `max_days_to_sell` | 3 | Buy no more than the market takes in this many days. |
| `neutral_cut` | 0.15 | Cut taken by the neutral Auction Houses. |
| `neutral_deposit_mult` | 5 | Neutral deposits compared with your faction's, until MyFA learns them from your posts. |
| `deposit_rate` | 0.20 | Deposit as a share of vendor price until MyFA sees you post (the classic 8-hour rule). |
| `default_sell_rate` | 0.6 | Share of listings assumed to sell until MyFA has your own sale mails. |
| `neutral_max_age_days` | 7 | Ignore neutral prices older than this. |
| `addon_updates` | auto | Who updates the in-game addon: `desk`, `curseforge`, or `auto` (CurseForge if you installed it from there). |

Desk reloads the config on every scan, so there's no need to restart it.

## The control bar

The top of the dashboard is MyFA Desk's control panel:

- **Status:** Watching (green), Reading scan, Paused, Waiting for first scan, Setup needed, or Problem, plus your realm, scan age, buy targets, flips ready to sell and number of characters.
- **New scan ready, refresh:** appears after each /reload. If the tab is in the background, it refreshes by itself.
- **Pause / Resume:** stop and restart reading new scans.
- **Check for updates:** turns gold as **Update to vX.Y.Z** when there's a new version. One click installs it (Desk and addon) and restarts Desk.
- **Settings:** WoW folder, account, Auction House cut, Windows notifications, update mode, **Add MyFA to desktop**, and an activity log.
- **Quit:** stops Desk. Double-click MyFA Desk to start it again. Starting it while it's already running just opens the dashboard.

The page is only reachable from your own PC. If port 47800 is taken, set `"port"` in `config.json`.

## Stopping and restarting

- **Stop:** press **Quit** in the top bar. Closing the browser tab doesn't stop Desk; it keeps watching in the background.
- **Tab closed?** Double-click MyFA Desk again. It finds the running copy and reopens its dashboard (it never starts a second copy), then press **Quit**.
- **Restarting is automatic when needed.** If the running copy is an older version, starting MyFA Desk replaces it. If it has frozen, starting MyFA Desk stops it and starts fresh.
- **Last resort:** Task Manager (Ctrl+Shift+Esc), find **Python** / **pythonw.exe**, **End task**.
- In terminal mode (`run_desk.bat`), press Ctrl+C or close the window.

Desk doesn't start with Windows; it runs only after you double-click it, and stops when you shut down.

## Updates

Desk checks [github.com/niranjraj/MyFa](https://github.com/niranjraj/MyFa/releases) for a new release each time it starts. When there is one, it asks, then updates itself and the MyFA addon in your `_forever_` folder; type `/reload` in game afterwards. Your `config.json`, price history, Targets.lua and any edits to `raids.json` are kept. If you edited `raids.json`, the new one is saved as `raids.new.json` next to it.

- In the app, **Check for updates** in the top bar checks right now. In the terminal, `run_desk.bat --update`; `--version` shows what you have.
- In `config.json`, `"auto_update"` can be `"ask"` (default), `"always"` or `"never"`.

## Raid calendar (`raids.json`)

Lists each raid's unlock date and the consumables and mats it uses, matched by exact item name. When Blizzard dates the next raids (spring and summer 2027 are announced without dates), add a line with the name and date. Add any consumable you trade to `items`; use `"raids": ["all"]` for things every raid needs. Desk rereads the file on every scan.

## Working with Claude

- Each run writes `claude_brief.md`, a compact summary of the scan. Upload it in your Claude chat for a session plan or deeper questions.
- Optional: set the `ANTHROPIC_API_KEY` environment variable and run `run_desk.bat --ask-claude`. Desk then asks Claude for a plan after every scan and shows it in a **Claude** tab in the report. This uses your API credits.

## Good to know

- Built and tested against a mocked WoW API, not the live Forever client. Real use is the first real test. If something errors, `/console scriptErrors 1` shows the message; send it to Claude and it can be fixed.
- Uses Forever's modern APIs: `C_AuctionHouse.ReplicateItems` for the full scan, commodity purchase calls for Buy, `C_TradeSkillUI` for recipes and `C_Container` for bags and bank. It reads both classic bank bags and modern bank tabs. If Blizzard changes these, the panel says so instead of breaking.
- Charts start filling in from your second day of scans. One scan a day is enough; more scans a day make the lines more accurate.
- Each ruleset and faction has its own Auction House, and Desk keeps them separate.
- History lives in `data\history.sqlite`. Delete it to start fresh.
