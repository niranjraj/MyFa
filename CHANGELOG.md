# Changelog

## 1.9.2
- **Gear upgrades count mana properly.**
  - Healers (Restoration Druid and Shaman, Holy and Discipline Priest, Holy Paladin) now value mana per 5s, Spirit and Intellect much more. A +healing piece no longer beats a Spirit/Intellect/mana piece just because it has more healing.
  - New **Mana or healing** choice per character: *Healing first* (short fights), *Balanced* or *Mana first* (long fights, leveling, PvP).
  - The **Change if you swap** column shows what you gain and, in red, what you lose from the item you wear now. In game, the tooltip says the same.
  - Each spec table shows the weights it used.
  - Your `stat_weights.json` gets the new healer values if you never edited it. Edited weights are left alone.

## 1.9.1
- **Gear tab no longer stays empty without saying why.** Desk and the in-game tab now name the missing step: addon too old, characters not seen yet, no gear listings in the scan, or stats not saved yet (a /reload before chat says "gear stats read").
- New `/myfa gear` command: what MyFA recorded (items worn, gear listings, stats read), whether it is still reading, and whether Desk's lists have arrived.
- Stats are now also read on clients without the tooltip data API (a hidden tooltip is used instead).
- Gear listed at the neutral Auction House counts too, marked "Neutral AH" when it's cheaper there.

## 1.9.0
- **Gear upgrades from the Auction House**, for any class and the specs you choose.
  - **What the addon records:** what each character wears (updated when you log in, change gear or level up). A Full scan also notes the cheapest listing of every armor piece and weapon, each random suffix ("of the Eagle") separately, and reads each item's stats in the background. Chat says when it's done.
  - **New Gear upgrades tab in MyFA Desk:**
    - per character, pick the class, main spec and off spec (all classic classes and specs, for example Druid Restoration, Balance, Feral (cat) or Feral (bear)), plus a PvP option that values Stamina more;
    - one list per spec: the slot, the item, its price, how much better it scores than what you wear, upgrade per gold, what it replaces and what it adds.
  - **Only gear you can use:** your level, your class's armor type (mail and plate from 40), weapon types, shields, relics and class-only items.
  - **Fair comparisons:** rings and trinkets are compared with your weaker one, and two-handers with your main hand and off hand together.
  - **Stat weights** are classic-style approximations. Edit them in `data/stat_weights.json` in the MyFA Desk folder.
- **New Gear tab in game:** upgrades for the character you're on. The button at the bottom switches between main and off spec; Search finds the item in the Auction House.
- The in-game panel is a little wider to fit six tabs.

## 1.8.1
- **Check Booty Bay Broker deals** (Flips tab). Open their WoW Forever deals page for your realm and faction, press Ctrl+A then Ctrl+C, and paste it into Desk. You can paste more pages one after another. Desk runs your flip checks on every row, using their sales figures (sold a day and range, selling speed, supply surge) and their usual sale price:
  - is there a gap between the lowest price and the next listing after you buy;
  - does it sell often enough;
  - is there a supply surge;
  - does it clear your profit after the cut.
  - Deals that pass become flips (marked *Booty Bay Broker*) and show on the in-game Buy list. The rest are listed with the reason they failed.
  - If your own scan is newer than theirs, MyFA trusts yours, and a cheap listing that's already gone is marked as such.
  - Pasted deals expire after 6 hours.
  - MyFA never fetches their site: their terms forbid automated scraping.
- **Partial buys:** if your gold or the market's daily sales only allow part of the cheapest listings, MyFA buys part of them. Days to sell then includes the cheaper ones left in front of yours.

## 1.8.0
- **Flips rebuilt around what actually sells.** Cheap listings alone don't make a flip; buyers do. Modelled on how market trackers like Booty Bay Broker judge deals.
  - **Sold a day:** each scan now remembers every listing (seller, size, price, time left). The next scan counts which ones disappeared before they could have run out: those were bought. Reposts by the same seller aren't counted, and listings that may just have expired only count at the high end of the range.
  - **Usual price:** the typical *sale* price over the last 7 days (from those sales), not the price of listings that may never sell.
  - **A flip needs all of this:**
    - it sells at least `min_sold_per_day` (1) a day;
    - you buy no more than the market takes in `max_days_to_sell` (3) days;
    - there's no supply flood (more than twice the usual amount listed, like a poison glut);
    - its sale price isn't falling;
    - it clears your profit and ROI after the cut, likely lost deposits and the 1s minimum deposit.
  - Flips rank by **gold a day**: profit per unit times how many sell a day.
  - The Flips tab shows sold a day (with its range), days to sell, gold a day and confidence, plus which cheap items were skipped and why.
- **Neutral AH trades** use the same rules for the house you sell to, with its own sales numbers. Resale prices are cut 15% while that house has under three days of history.
- **Raid buys** are skipped for items that don't sell on your market even now.
- **In game:** Buy rows show how many sell a day. After each scan, chat says whether sales were measured, or reminds you to scan again 20 minutes to a few hours later.
- **New settings:** `min_sold_per_day`, `max_days_to_sell`.

## 1.7.2
- **Flips now relist at a price that sells.** Before, MyFA bought what was listed under 70% of a "market" price and told you to relist at that market price. Cheaper listings were still there, so yours didn't sell. Now:
  - MyFA works out which cheap listings to buy so that, afterwards, **you are the cheapest seller**.
  - **Relist at** is the next listing left after your purchase, never above where the item usually bottoms out (its typical daily lowest price over the last two weeks).
  - It only suggests a flip if you can buy everything under your relist price (within your supply and gold limits).
  - The reason now says exactly that, for example *"Buy all 20 listed at up to 3s. That leaves 6s 50c as the cheapest listing: relist at 6s 50c and yours sell first."*
- The same realistic price is used for neutral AH trades (match the cheapest listing there, capped by its usual low) and raid buys (no more "+15%" guess).
- My flips: **Aim to sell at** now matches the cheapest listing (never under your alert price) instead of a higher market estimate.
- `flip_threshold` is no longer used for flips.

## 1.7.1
- **How long your auctions have been up.** The Listed tab (and Desk's new **Your auctions** table on My flips) shows:
  - how long you've been trying to sell each item, counted back through relists to your last sale;
  - how many times you've relisted it;
  - how long is left on the current auction.
  Auctions posted where MyFA couldn't see the post count from the first time MyFA saw them listed.
- **Price fell** (new): when the whole market has dropped below what you paid, MyFA says so. It tells you your price won't sell and every relist costs a deposit, shows the loss if you sell near the market, and mentions the usual price if holding may recover it. 1.7.0 wrongly told you to keep your price in this case.
- **Cheap dump** (new): a few units dumped cheap while most of the supply still sells above your floor. MyFA tells you to leave yours, or repost at where the supply sits if you're well above it, and points out when buying the dumped ones is a flip.
- **Too high**: flagged when your price is more than 1.5 times where the item trades.
- Opening the Auction House warns about auctions whose market fell, as well as undercuts.
- My flips tooltips say how long ago you bought.

## 1.7.0
- **Posting helper.** Rows on the Sell tab show MyFA's plan, for example *post 20 at 3s 61c, 24 Hours*. Press **Post** and MyFA puts the item in Blizzard's sell window and fills in the price, quantity and duration; you check it and press Post there. MyFA never posts for you.
  - **Price:** the cheapest listing from another seller (live when your Auction House window has just searched it), never below your floor. The floor is what you paid plus the cut and likely lost deposits, or the vendor price for things you didn't buy.
  - **Quantity:** at most about half of what's listed, so you don't flood the market.
  - **Duration:** the longest one whose deposit you can afford to lose, given how often the item sells for you.
  - **Warning:** shown when the deposit is too high for something that rarely sells, with what a vendor pays instead.
- **Listed tab: undercut check.** Shows your auctions at this Auction House and flags the ones someone lists cheaper (UNDERCUT, with a "repost at" price), the ones where the cheaper seller is under your floor (keep yours), and the ones where you're the lowest.
  - **Check prices** looks up live prices, one search at a time with a pause between them. It only reads prices.
  - **Cancel** cancels one auction per click.
  - Opening the Auction House tells you in chat if any of your auctions look undercut.
- Full scans now note the cheapest listing from someone other than you, so your own auctions don't hide an undercut.
- **CurseForge ready:**
  - Desk now also keeps your targets in a small **MyFA_Desk** folder next to the addon, so addon updates (including the CurseForge app's) don't wipe them. If they are replaced, Desk writes them again.
  - New setting **In-game addon updated by** (Automatic / MyFA Desk / CurseForge app). On Automatic, Desk leaves the addon alone when it came from CurseForge.
  - Releases upload the addon to CurseForge automatically once the token and project ID are set (see README).

## 1.6.0
- **Real profit from your sales.** When you open a mailbox, MyFA now reads "Auction successful", "Auction expired" and "Auction cancelled" mails as well as "Auction won":
  - A sale closes your flip with the real profit, after the cut, against what you paid (oldest purchases first). Chat shows it, for example *SOLD 6 Wild Steelbloom for 1g 42s after the cut: +46s 50c on your flip.*
  - Expired and cancelled auctions record the deposit you lost.
  - Each mail is counted once, even when two sales are identical.
- **Deposits recorded when you post.** MyFA notes each listing and the deposit you paid, and learns your deposit rate. Items listed on the Auction House still count as yours ("on AH") in My flips and tooltips.
- **Deposit risk in every profit figure.** MyFA works out how often each item sells for you and takes the deposits you'd lose relisting it off flips, crafts, sell suggestions, alert prices and neutral trades. Until it has your own sales it assumes 60% of listings sell.
- **New Profit tab** in MyFA Desk: what flips, raid holds, crafts and farmed or looted items really made over 7 days, 30 days and all time; profit by day; how each item sells; items that keep coming back unsold; and every sale and lost deposit. In game: `/myfa profit`, a 7-day line on My flips, and "your sales" in item tooltips.
- **Neutral Auction House trading** (Gadgetzan, Booty Bay, Everlook):
  - MyFA recognises a neutral Auction House and keeps its scans separate from your faction's (`/myfa ah neutral|faction|auto` if it guesses wrong).
  - New **Neutral AH** tab in Desk shows three lists: buy on the neutral AH and sell at home, buy at home and sell on the neutral AH, and things you own that fetch more there. All use its 15% cut and higher deposits.
  - In game, the Buy and Sell tabs switch to the neutral lists when you stand at a neutral Auction House. Home Buy rows that go to the neutral AH are marked TO NEUTRAL. Tooltips show the neutral price.
- New settings: `neutral_cut`, `neutral_deposit_mult`, `deposit_rate`, `default_sell_rate`, `neutral_max_age_days`.

## 1.5.2
- Purchases show in My flips straight away. Bought items wait in the mailbox, and MyFA used to hide a flip until it saw them there. Now anything bought since you last opened the mailbox counts as "on its way, mail".
- Backup purchase tracking: when you open the mailbox, MyFA reads your "Auction won" mails (item, quantity, price paid) and records any purchase it missed. This covers buys made through another auction addon that MyFA's hook can't see. Purchases it already recorded aren't added twice, and "sold" mails are ignored.
- `/myfa status` shows your MyFA version and when the last purchase was recorded.

## 1.5.1
- Starting MyFA Desk while it's already running now checks the running copy:
  - **Same version, answering:** it just opens its dashboard. Only one copy ever runs.
  - **Older version:** it asks the old copy to quit and starts the new one.
  - **Frozen (port taken, no answer):** it stops that copy (only the one MyFA recorded) and starts fresh.
  - **Port taken by a different program:** it leaves that program alone and opens a page explaining what to do.
- On Windows the dashboard's port is now held exclusively, so a second copy can't share it by accident.

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
