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

- **Automatic tracking:** every Auction House purchase is recorded, whether you buy through the MyFA panel, the Blizzard window or another addon. For something you bought before installing MyFA, shift-click it into `/myfa bought [item] qty price`, for example `/myfa bought [Golden Sansam] 20 14s50c`.
- **Alerts:** when the lowest listing clears your profit target, you get a raid-warning message, a sound and a chat line naming the character and bag, bank or mailbox that holds it. The default target is 15% after the cut; change it with `/myfa roi 20`. Checks run after every scan, when you open the Auction House and when you log in. Repeats come at most every 12 hours, or sooner if the price climbs another 10%.
- **Desk:** prints the same alert and shows a Windows notification. Turn that off with `"desktop_notifications": false`.
- **Raid items:** if the item is also a raid consumable, the alert says so, because launch week usually pays more and you may want to hold.
- **Where to see them:** the **My flips** tab in game and **My flips** in Desk list what you paid, the price now, the alert price, the profit now and a note.
- **Stop tracking** an item with `/myfa forget [item]`. Turn alerts off with `/myfa alerts off`.

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
