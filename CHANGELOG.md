# Changelog

All notable changes to Sapphire. The in-app updater shows the newest section
as "What's new".

## 1.4.4 — 2026-10-24

### Added
- **Camera fix for skins made before Deadlock's camera update.** That update
  turned the camera and aim points on every hero model by 120°, so older skins
  put the first-person camera in the wrong place. When you apply, Sapphire now
  checks each skin's model against the one in your installed game and, if it's
  in the old layout, moves its camera points to the new one, keeping any offsets
  the author made. Fixed models go in their own file loaded ahead of your mods;
  the mod files themselves are never changed. Mods it fixed show a "Camera
  fixed" badge; ones it couldn't safely fix show "Camera: check". On by default,
  Settings → Behaviour to turn it off. Ported from Deadlock Mod Manager.

### Fixed
- **Update all queued mods again** when pressed while they were already
  downloading (5 updates became 40 downloads). A mod can now only have one
  install or update in progress; the button shows "Updating…" until they finish.

## 1.4.3 — 2026-10-18

### Added
- **Install a mod's optional files alongside the main one.** Mods like QOL Lock
  ship a main download plus optional add-ons (extra announcers, icon packs…).
  In Browse, each file of a mod you already have now shows **Add** next to
  **Replace**: Add installs it as its own entry beside the main one (named
  "Mod + file"), with its own on/off, load-order slot and update checks. The
  import from DMM/Grimoire keeps such extras too instead of overwriting.

### Fixed
- **Settings page squashed in a short window.** The sections overlapped and
  text was clipped when the window was small or windowed. Settings now scrolls.
- **Update checks for mods with several files.** A mod's other files (optional
  add-ons, other colours) were offered as "updates" to the file you had. An
  update is now only a newer file that replaces yours: same file name family
  (version numbers and dates ignored), or anything live once your file is
  archived or removed.

## 1.4.2 — 2026-10-18

### Fixed
- **"Get other variants" showed nothing.** It re-downloaded the same file, and
  most GameBanana mods ship each colour or style as a *separate* file, so there
  was nothing new to show. The button is now **Other variants…**: it lists every
  file the mod has on GameBanana (name, size, date, the author's notes, with
  the installed one marked) and you pick the one to switch to. Picking the file
  you already have downloads it again and keeps every VPK inside it, for mods
  that bundle their variants in one file.

## 1.4.1 — 2026-10-18

### Added
- **Switch variants without re-downloading.** Every VPK a download ships is now
  kept in the library, and the Installed panel has a Variants section with a
  tick box per part. Mods installed before this version only kept the parts you
  chose; a "Get other variants" button fetches the rest once.

## 1.4.0 — 2026-10-18

### Added
- **Downloads page.** Every install, update and import this session with live
  progress, cancel per item or all, retry for failures, and a count in the nav.
- **Grid view for Installed**, now the default (List is still there). Cards show
  the load-order number, an on/off box, update and conflict badges, and you
  drag them to reorder just like the list.
- **Sort by most downloaded** in Browse.
- The Installed page's detail panel now shows the mod's preview image.
- **Discord Rich Presence**, off by default. Settings → Discord; needs a Discord
  Application ID (free, two minutes at discord.com/developers). Talks only to
  the Discord app on this computer.

### Fixed
- A long file name (no spaces, so it couldn't wrap) pushed the Install button
  off the edge of the details panel. File names are now shortened in the
  middle with the full name on hover, and the panel can't be widened by its
  contents any more.

## 1.3.1 — 2026-10-17

### Fixed
- **Installing mods failed** with "GameBanana error: INPUT_ERRORS" / HTTP 400. The
  mod details request asked for two fields GameBanana doesn't accept. It now
  uses the full profile endpoint, the same one Deadlock Mod Manager uses.
- **Sorting while searching.** GameBanana's search ignores the sort order, so
  Sapphire now sorts search results itself by the chosen option (most liked,
  most viewed, newest, recently updated). Plain browsing was already sorted by
  the server.

### Added
- **Check for updates** now shows a popup listing the mods with updates (with an
  Update all button), or confirms everything is current.
- **Clear all data** in Settings → Game files: removes every mod and profile
  from Sapphire and the game for a fresh start. Settings and the Deadlock folder
  are kept.

## 1.3.0 — 2026-10-17

### Added
- **Themes and custom colours.** Six presets (Sapphire, Amber Hand, Patina,
  Midnight, Oxblood, Parchment) in Settings → Appearance, and a colour picker
  for every part of the interface: background, panels, controls, lines, accent,
  text, muted text. Changes apply live.
- **Interface size.** Small, Normal, Large or Huge, in Settings → Appearance.
- **List view in Browse.** A Grid/List toggle above the catalogue; the list
  shows more mods per screen with the same badges and details.
- **Reapply button** on the Installed page: turns every mod off and back on by
  rewriting all files in the game's addons folder and re-checking gameinfo.gi.
- **Profiles-only import.** The import dialog can bring over just profiles from
  Deadlock Mod Manager or Grimoire and match them to mods already installed.
  Re-importing refreshes profiles that came from the same manager and leaves
  ones you made yourself alone.
- This changelog, which the updater reads for release notes.

### Fixed
- Dragging a mod towards the top or bottom of the Installed list now scrolls
  the list, so long lists can be reordered in one drag.

## 1.2.0 — 2026-10-17

### Added
- **Self-update.** Sapphire checks GitHub on start and every few hours
  (latest release, or the version on `main`), shows an update bar, installs
  the new version into its own environment and offers a restart. Mods,
  profiles and settings are untouched.
- Settings → Check for updates, with the current version shown.

## 1.1.0 — 2026-10-17

### Added
- **Identify unknown mods.** Fingerprints a VPK (SHA-256 plus a content
  signature of its file list) and looks it up in the community hash index that
  Deadlock Mod Manager runs. A match gives a manually added mod its real name,
  thumbnail, GameBanana link and update checks. Duplicates of mods you already
  have are removed.
- **Import from Deadlock Mod Manager and Grimoire.** Reads their records,
  copies mods into the library with names and GameBanana IDs, keeps load order
  and on/off state, recreates profiles, and re-downloads mods whose files are
  gone. Offered in the setup wizard and in Settings.
- Files that DMM or Grimoire left in the addons folder are adopted with their
  proper names the first time you apply, even without importing.

### Fixed
- Grimoire's own `citadel/grimoire` search path is cleaned out of gameinfo.gi.

## 1.0.0 — 2026-10-17

First release.

- Browse GameBanana live: mods and sounds, search, sort, category and hero
  tree, author filter, hide 18+ / outdated / installed.
- One-click install with a variant picker; install from a pasted link or a
  dropped file.
- Load order by drag, with per-file conflict detection.
- Mod update checks and Update all.
- Profiles.
- Automatic repair of gameinfo.gi after game updates.
- Setup wizard.
- Native Steam, Flatpak and Snap detection on Ubuntu and Bazzite.
