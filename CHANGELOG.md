# Changelog

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
