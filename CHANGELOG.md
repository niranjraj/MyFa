# Changelog

## 1.5.0
- The Guide can now use your Claude plan instead of API credit, in two ways:
  - **Claude Code (one click):** if Claude Code is installed on your PC and logged in with your Claude account, **Fetch guide** runs it in the background with web search. It counts against your plan's usage, not API credit.
  - **Claude chat (no install):** **Copy request** copies a ready-made request with your characters and prices, **Open Claude** opens a new chat, and you paste Claude's answer into **Save to Guide**.
- **Settings > Guide uses:** Automatic (Claude Code if installed, otherwise Claude chat), Claude Code, Claude chat, or Claude API key. The API key is optional now.

## 1.4.0
- **Add flips by hand.** In game: **+ Add flip** on the My flips tab (or `/myfa add`). Drag the item in from your bags, shift-click it, or type its name, then enter quantity and price each. In MyFA Desk: the **Add a flip** form on My flips, with item-name suggestions and an optional date. Desk-added flips reach the addon on your next /reload.
- **Remove** button on each row of Desk's My flips stops tracking that flip, in Desk and in game.
- New **Guide** tab in MyFA Desk:
  - **Your characters:** level, race and class, zone, profession skills and gold for each character, recorded by the addon.
  - **Your next moves:** the best things to do right now, ranked by gold, from your own scans, bags, bank and recipes. It also gives gathering advice limited to what your skill can pick, and reminds you when a profession is at its skill cap.
  - **Researched guide:** press **Fetch guide** and Claude searches Wowhead and current WoW Forever guides for your level, class and professions, using your scan prices. You get quests that pay, profession next steps, farms, items to watch and recent Forever changes, with sources. Needs your Claude API key (Settings or the Guide tab; stored only on your PC). Each fetch costs a few cents. Terminal: `run_desk.bat --guide`.
- The addon records each character's level, class, race, zone and profession skills.
- Raid stock-up buys now respect your per-item gold limit.

## 1.3.0
- Scan progress bar: "Asking the server for every auction... 12s", then "Reading auctions 45% (12,300 of 27,400)", then "Done". The server doesn't report progress while it prepares the list, so that part shows a moving bar and a seconds counter.
- Scans no longer get stuck on "Waiting for server". MyFA also watches the list size, so it carries on if the server's signal never comes, and gives up after 2 minutes with a message.
- Closing the Auction House during a scan stops it cleanly with a message. Closing only the MyFA panel doesn't stop it.
- A "Next:" line under the header always says what to do now: press Full scan, type /reload, /reload again once Desk has read it, or check My flips when something is ready to sell.
- Every row has a label: FLIP, VENDOR, RAID or SNIPE on Buy; SELL, VENDOR, CRAFT or KEEP on Sell; CRAFT on Craft; SELL NOW, HOLD, BELOW COST or NO PRICE on My flips.
- Hover a row for step-by-step instructions (what to press, the most to pay, what to post it at, where the item is). Hover a tab for what it's for.

## 1.2.1
- Clearer panel: tabs are now **Buy**, **Sell**, **Craft** and **My flips**. A line under the tabs explains each one and what its right-hand number means. Rows read in plain words, for example "buy x2, max 74g 20s each" or "post at 35c each".
- Docking now finds auction windows that other addons place inside Blizzard's Auction House frame, such as wider "market" windows. It also learns which windows close with the Auction House, so it docks right the next time.
- Thin markets (fewer than 10 listed, often recipes and patterns) are no longer Buy targets. They show as high-risk snipes at the bottom of Desk's Flips tab (`"include_snipes": true` puts them back in game).
- The in-game Sell list skips stacks worth under 1s (`"min_item_value"` in config.json).

## 1.2.0
- No more terminal: double-click **MyFA Desk.pyw** and Desk runs quietly in the background. It opens your dashboard as a live app in the browser.
- Control bar on the dashboard: status (watching, paused, setup needed), a "New scan ready" button after each /reload, Pause/Resume, Check for updates (turns gold when one is out; one click installs it and restarts), Settings and Quit.
- Settings in the page: WoW Forever folder (with Find it), account, Auction House cut, Windows notifications, update mode, and "Add MyFA to desktop" for a desktop shortcut.
- First-run setup happens in the page instead of a terminal prompt. An activity log shows what Desk is doing.
- Only your own PC can reach the page (127.0.0.1); other websites can't control it.
- `run_desk.bat` still works if you prefer the terminal.
- After updating from 1.1.0 in the terminal, close it and start **MyFA Desk.pyw** from now on.

## 1.1.0
- The panel docks beside whichever Auction House window is open (Blizzard's or another addon's, such as a custom market window) and remembers where you drag it. `/myfa dock` snaps it back.
- Flip tracking: every Auction House purchase is recorded automatically, from the MyFA panel, the Blizzard window or another addon. Add older purchases with `/myfa bought [item] qty price`.
- Sell alerts: when a flip's lowest price clears your profit target (15% after the cut by default, `/myfa roi 20` to change), you get an on-screen warning, a sound and a chat line saying which character and bag, bank or mailbox has it. MyFA Desk also sends a Windows notification.
- New Mine tab in game and My flips tab in Desk: what you paid, price now, alert price, profit now, plus raid and trend notes.
- Multiple characters: bags, bank and mailbox are combined across every character on the same Auction House, with per-character locations in the panel, tooltips ("you own", "you paid") and Desk. Gold is totalled across characters.

## 1.0.0
- First release of MyFA for WoW Forever (Interface 16001).
- Addon: full Auction House scan, bags + bank snapshot, recipes from every profession, Buy / Items / Craft panel with Search and Buy-with-Confirm, price tooltips. `/myfa` opens the panel.
- Desk: flips, vendor flips, best use of everything you own, crafts from stock, gathering values, price-history charts, and an Analysis tab with raid prep for the 9 Dec 2026 raids, market index, flip bands, weekday pattern and a flipping playbook.
- Desk checks GitHub for new releases on start and updates itself and the addon.
