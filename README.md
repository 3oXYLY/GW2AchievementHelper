# GW2 Achievement Helper

**Version 1.0.0** · Made by **F_oxy**

A desktop app for Guild Wars 2 players. It reads your achievements with your own API key, lets you browse and search them in a layout inspired by the in-game Achievements panel, and finds guides for anything you're stuck on.

Everything runs on your computer. There is no server and no account to create.

## Getting started

1. Extract the zip and double-click **GW2AchievementHelper.exe**. No Python or other installs are needed.
   - Keep the `_internal` folder next to the exe; the app needs it. To move the app, move the whole folder.
   - Tip: right-click the exe → **Send to → Desktop (create shortcut)**.
2. Windows may show *"Windows protected your PC"* the first time, because the app isn't code-signed. Click **More info → Run anyway**.
3. The app asks for an API key:
   - Open [account.arena.net/applications](https://account.arena.net/applications) (there's a button for it in the app) and click **New Key**.
   - Give it any name and tick only **account** and **progression**.
   - Paste the key into the app and click **Save & sync**.

The first sync downloads the full achievement database (about a minute). After that everything is stored locally and later syncs only fetch your progress.

**Requirements:** Windows 10 or 11 (64-bit).

## What you can do

### Navigation (left side)

| Entry | What it shows |
|---|---|
| **Summary** | Recently completed, nearly completed, mastery points per region, and your achievement points |
| **Watch List** | Achievements you've starred |
| **Nearly Completed** | Everything that's 80% or more done |
| **All Achievements** | The full list |
| **Expansions / sections** | Each section with its categories and your completion % |

The **search box** at the top left searches names, descriptions, requirements, categories and your own notes.

### Header

Your total achievement points (permanent + daily), the next reward milestones, and how many points you need for the next one.

### Achievement list

- **Filters:** status (not done / in progress / done), reward (mastery point for any or a specific region, title, item), sort order.
- **Search saved wiki pages:** also searches inside wiki pages saved on your computer.
- **Right-click** an achievement to add it to your watch list, find guides, or open the wiki text.

### Details panel

- Requirement, tiers, and which collection items you still need, with icons.
- **Trading Post prices** for each missing item, and the **cost to finish** the collection (buying now vs. with buy orders). Prices refresh every 15 minutes.
- Rewards and prerequisite achievements.
- **My notes:** write anything; it's saved automatically.
- **Web guides:** searches the web and lists results inside the app. Known GW2 sites (wiki, Reddit, YouTube…) are marked with ★ and listed first.
- **Wiki text:** the achievement's wiki page inside the app. If the wiki is down, the app uses the latest good copy from web.archive.org and shows its date.

### Offline wiki library (optional, off by default)

The app can download the wiki page for each of your achievements so explanations open instantly and still work when the wiki is down.

- After the first sync the app explains the feature once and asks whether to turn it on.
- It downloads slowly on purpose (about one page every two seconds) and only while the wiki is online.
- **Pause / Resume** any time from the button at the bottom of the window, or in **Settings → Offline wiki library**.

### Settings

API key, achievement language, theme (**Tyria** game style, Dark, Light), the offline wiki library, and your data folder.

### Shortcuts

- **F5**: sync
- **Ctrl+F**: search

## Privacy and security

- Your API key and all data are stored in your Windows user folder: `%LOCALAPPDATA%\GW2AchievementHelper`. Nothing is stored in the program folder, so you can share it and everyone starts empty with their own key.
- The API key is encrypted with **Windows DPAPI**, so only your Windows user on your computer can read it.
- The key is only ever sent to `api.guildwars2.com` (in a request header, never in a URL).
- Icons are only downloaded from `render.guildwars2.com`.
- Web searches only send the achievement name, never account data.
- GW2 API keys are read-only: they can't change anything on your account.
- **Settings → Remove key & all my data** deletes everything the app stored.

## Notes

- If Windows Defender or another antivirus blocks the app, it's a false alarm that's common with Python apps packaged as an exe. You can check it on [VirusTotal](https://www.virustotal.com) and allow it in **Windows Security → Virus & threat protection → Protection history**.
- ArenaNet's API can lag a little behind the game. If new progress doesn't show up, wait a moment and sync again.
- The app's achievement point total can differ slightly from the game, because a few old achievements are reported differently by the API. **Summary → Points details** shows exactly how the total is calculated.
- If web search stops working (search engines sometimes block automated requests), the **Open directly** buttons open the same search in your browser.
- If something goes wrong, details are written to `app.log` in the data folder (**Settings → Open folder**).

## For developers

The full Python source is on GitHub, and also in the `source` folder of the download.

- **Run from source:** install Python 3.9+, then double-click `run.bat` (it installs PySide6 the first time), or run `python -m pip install -r requirements.txt` and `python main.py`.
- **Build the exe:** double-click `build_exe.bat`. The result is the `dist\GW2AchievementHelper` folder (the exe plus its `_internal` folder).

Project layout:

```
main.py             entry point
gw2ach/api.py       GW2 API client
gw2ach/storage.py   local SQLite database
gw2ach/sync.py      syncing, names, prices
gw2ach/model.py     calculations and text for the UI
gw2ach/guides.py    web search and wiki / web archive
gw2ach/library.py   offline wiki library downloader
gw2ach/icons.py     icon cache
gw2ach/secret.py    API key encryption (DPAPI)
gw2ach/ui/          Qt interface (one file per part of the window)
assets/             app icon
version_info.txt    exe file details (name, version, author)
```

## Credits

- Made by **F_oxy**.
- Achievement point icon based on the icon set from [gw2treasures.com](https://github.com/GW2Treasures/gw2treasures.com) (MIT License, see `THIRD-PARTY-NOTICES.txt`).
- Game data and icons come from the official Guild Wars 2 API.

## Legal

This is an unofficial, fan-made tool. It is not affiliated with or endorsed by ArenaNet or NCSOFT. Guild Wars 2, ArenaNet and all related logos and designs are trademarks or registered trademarks of NCSOFT Corporation. Game content and materials are © ArenaNet, LLC.
