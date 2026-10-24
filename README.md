# Sapphire

A fast, reliable Deadlock mod manager for Linux. Browse GameBanana live, install
with one click, drag mods into the order you want, see exactly which mods clash,
and keep everything working after game updates.

Works the same on **Ubuntu** and **Bazzite** (and other Linux desktops). Finds
Deadlock whether Steam is native, Flatpak or Snap, on any library drive.

## Install

```sh
git clone https://github.com/SnowberriFox/Saphire.git
cd Saphire
bash install.sh
```

That's it. Sapphire appears in your app menu. The installer:

- needs no `sudo`, so it works on immutable systems like Bazzite
- installs everything into your home folder (`~/.local/share/sapphire`)
- downloads its own Python and Qt through [uv](https://docs.astral.sh/uv/), so it
  doesn't care what Python your system has
- bundles 7-Zip so `.rar` and `.7z` mods work out of the box

## Updating

Sapphire updates itself. It checks GitHub on start and every few hours; when a
newer version exists, a bar appears at the top with an **Update** button. The
update is downloaded and installed into Sapphire's own folder, then you restart
it. Mods, profiles and settings are untouched. Settings → Check for updates does
the same on demand.

It looks for the latest GitHub release first, and if there are no releases, for
the version number on the `main` branch. So to ship an update: bump
`__version__` in `sapphire/__init__.py` (and `version` in `pyproject.toml`),
push to `main`, and every install picks it up. Tagging a release (`v1.3.0`) on
GitHub works too and lets you attach notes.

If you're running from a git clone with `python -m sapphire`, the updater steps
aside and you use `git pull` instead.

To uninstall: `./uninstall.sh` (keeps your mod library) or `./uninstall.sh --purge`.

## Using it

- **First run**: a short setup wizard confirms the third-party content notice, finds
  Deadlock, offers to import mods you already have, and checks GameBanana is
  reachable. Run it again any time from Settings.
- **Appearance**: Settings → Appearance has six colour themes, a colour picker for
  every part of the interface, and four interface sizes. Browse has a Grid/List
  toggle.
- **Browse**: live GameBanana catalogue. Filter by category or hero (type to find
  one), sort, search, switch between mods and sounds, hide 18+, outdated or
  already-installed mods. Click an author's name to see everything they've made.
  Paste a GameBanana link to install it directly.
- **Installed**: drag to set priority. **Higher in the list wins** when two mods
  change the same file. Each mod shows whether it wins or gets overridden, and the
  side panel lists the exact files. Tick boxes turn mods on and off.
- **Profiles**: save a setup (which mods are on plus their order) and switch in one
  click.
- **Downloads**: a page listing every install and update with progress, cancel and
  retry. Downloads run one at a time in the order you started them.
- **Discord**: optional Rich Presence (Settings → Discord). It needs a Discord
  Application ID, which anyone can create for free at
  discord.com/developers/applications; one ID can be shared.
- **Sound previews, favourites, collections**: ▶ Preview on sound mods, ☆ to save
  a mod for later ("Only my favourites" lists them), and paste a GameBanana
  collection link to install its mods in one go.
- **Share profiles**: Profiles → "Share as a file…" / "Import a profile file…".
  Importing downloads whatever GameBanana mods are missing.
- **Roll back**: every update keeps the previous version; "Roll back" swaps it in.
- **Settings → Behaviour**: install updates automatically, one skin per hero, and
  a background helper that keeps mods loading after game updates while Sapphire
  is closed (an XDG autostart entry, `~/.config/autostart/sapphire-helper.desktop`).
- **Camera fix for older skins** (on by default, Settings → Behaviour): a Deadlock
  update turned every hero's camera attachments by 120°, so skins compiled before
  it put the first-person camera in the wrong spot. On apply, Sapphire converts
  the winning copy of each affected hero model to the current layout (keeping the
  author's own offsets) and loads it from an overlay `pak01_dir.vpk` in front of
  your mods. Mod files are never changed. Ported from Deadlock Mod Manager's
  camera-frame repair; anything it can't convert safely is left alone and flagged.
- **Reapply** (Installed page): turns every mod off and back on by rewriting the
  whole addons folder, for when something looks wrong in game.
- **Launch Deadlock**: applies everything, double-checks `gameinfo.gi`, then
  starts the game through Steam.

You can also drag `.zip`, `.7z`, `.rar` or `.vpk` files onto the window to add them.

- **Identify unknown**: a mod added by hand (or found in your addons folder) shows
  as a "Manual install". Identify fingerprints the VPK and looks it up in the
  community hash index that Deadlock Mod Manager runs, so it gets its real name,
  thumbnail, GameBanana link and update checks. Nothing but file hashes is sent.
- **Switching from Deadlock Mod Manager or Grimoire**: Settings → Import. Sapphire
  reads their records (DMM's `state.json` and download cache; Grimoire's
  `mod-metadata.json` and `profiles.json`), copies the mods into its library with
  their names and GameBanana IDs, keeps the load order and on/off state, and
  recreates each profile. Mods whose files are gone are re-downloaded from
  GameBanana. Neither manager's data is changed. Even without importing, files
  those managers left in the addons folder are adopted with their proper names
  the first time you apply.

If a download contains several VPKs (colour variants, optional parts), Sapphire
asks which ones you want and remembers your choice for future updates.

## How it works (and why it's reliable)

1. **Your mods live in Sapphire's library**, not in the game folder:
   `~/.local/share/sapphire/library`. Reinstalling or verifying the game never
   loses them.
2. **The game's `addons` folder is generated** from your load order every time you
   apply. Sapphire works out exactly which `pakNN_dir.vpk` files should exist, skips
   ones that are already right, writes changed ones atomically, and removes
   leftovers. It only ever touches `pakNN_*.vpk` files. Files are hard-linked from
   the library when the game is on the same drive (instant, no extra space) and
   copied otherwise.
3. **More than 99 mods?** Deadlock only loads 99 per folder, so Sapphire spills
   over into `addons2`, `addons3` and so on, in priority order.
4. **`gameinfo.gi` gets one small, clearly marked block** inserted before
   `Game citadel`. Nothing else in the file is changed, including Windows line
   endings. If you used another mod manager before, its edits are cleaned up.
5. **Game updates** replace `gameinfo.gi`. Sapphire watches the file and puts the
   block back automatically, and re-checks before every launch.
6. **Mods you added by hand** to `addons` are adopted into the library (shown as
   "Manual install") instead of being deleted.
7. **Nothing is changed while Deadlock is running.** Changes queue up and apply as
   soon as you close the game.

## Troubleshooting

- **"Deadlock not found"**: Settings → Choose… and pick the `Deadlock` folder (the
  one containing `game`). Steam → Deadlock → Manage → Browse local files shows it.
- **Mods not showing in game**: launch through Sapphire's button once, or use
  Settings → Re-check gameinfo.gi. If you launch from Steam right after a game
  update with Sapphire closed, that session runs unmodded.
- **Start completely fresh**: Settings → "Turn everything off and restore the game".
- **Logs**: Settings → Open log file (`~/.local/share/sapphire/sapphire.log`).

Only use cosmetic mods. Valve allows client-side visual and audio mods; anything
that gives a gameplay advantage can get you banned.

## Development

```sh
uv venv && uv pip install -e '.[dev]'
.venv/bin/python -m pytest          # unit + integration tests
.venv/bin/python -m sapphire        # run from source
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/ui_smoke.py /tmp/shots   # UI screenshots with fake data
```

Code map:

| File | What it does |
|---|---|
| `sapphire/gamebanana.py` | GameBanana apiv11 client (browse, search, categories, files, downloads) |
| `sapphire/steam.py` | Finds Steam and Deadlock, detects if the game is running, launches it |
| `sapphire/gameinfo.py` | Adds/removes the marked block in `gameinfo.gi` |
| `sapphire/vpk.py` | Reads VPK file lists (for conflict detection) |
| `sapphire/archive.py` | Safe extraction of zip/7z/rar |
| `sapphire/deploy.py` | Turns the load order into files in `addons*` |
| `sapphire/library.py` | Saved state: mods, order, profiles (atomic JSON) |
| `sapphire/identify.py` | Fingerprints a VPK and asks the hash index which mod it is |
| `sapphire/importers.py` | Reads Deadlock Mod Manager and Grimoire data into an import plan |
| `sapphire/core.py` | The manager: install, update, apply, profiles, import, identify |
| `sapphire/updater.py` | Checks GitHub for a newer Sapphire and installs it in place |
| `sapphire/discord.py` | Discord Rich Presence over the local IPC socket |
| `sapphire/ui/` | The Qt interface (`onboarding.py` is the first-run wizard, `theme.py` the themes) |

Data lives in `~/.local/share/sapphire` (`SAPPHIRE_HOME` overrides it, handy for
testing). Set `SAPPHIRE_DEBUG=1` for verbose logs in the terminal.
