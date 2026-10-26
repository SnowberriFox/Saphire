# Changelog

All notable changes to Sapphire. The in-app updater shows the newest section
as "What's new".

## 1.8.0 — 2026-10-26

### Added
- **See which heroes a mod really changes.** The side panel has a new "Heroes it
  changes" section (model, textures, portraits, menu scenes), worked out from
  the mod's files rather than its GameBanana title. Sapphire reads the hero list
  from the game itself, so renamed heroes come out right (Vyper's portraits are
  still filed under "kali", Abrams's under "bull") and new heroes work as soon as
  the game has them.
- **A heads-up when a mod changes a hero it doesn't mention:** an "Also changes
  …" badge and a note in the side panel. This is what Ham's "profiles leak
  into each other" report turned out to be: a sound mod ("Celeste Balatro Mult
  Ult") that ships a whole Billy reskin, so Billy looked different whatever the
  other mods said. Sapphire was deploying the profile correctly; the mod just
  does more than its title says. Skins that don't name any hero aren't flagged.

## 1.7.2 — 2026-10-25

### Fixed
- **The padlock on locked mods was hidden under the tick box** in List view on
  desktops whose theme puts the tick box at the very edge of the row (KDE's, for
  one). The padlock now has its own spot between the tick box and the mod's
  number, wherever the theme puts the box.

## 1.7.1 — 2026-10-24

### Fixed
- **Patch notes were empty after updating** ("No patch notes came with this
  version"). The in-app updater skips links inside a download for safety, and the
  notes were shipped as one; they're now a real file. The window now also lists
  earlier versions below the new ones, and links to GitHub if the notes are ever
  missing.

## 1.7.0 — 2026-10-24

### Added
- **Priority list** (Installed → Priority…). Every mod in load order as one
  compact list, top wins: drag rows, use Move to top / Up / Down / Move to bottom,
  or type the number a mod should have. A find box jumps to a mod. Nothing changes
  until you press Save.
- **Lock a mod in place.** A locked mod keeps its number (#3 stays #3) while you
  drag other mods, install new ones or remove old ones; everything else moves
  around it. Lock from the Priority list, the side panel's new Load order section,
  or by right-clicking a mod. Locked mods show a padlock.
- **Patch notes when Sapphire opens.** After an update, Sapphire shows what
  changed since the version you had (or every time it opens, or never: your
  choice, at the bottom of the window). Settings → Sapphire → Patch notes opens
  them any time.

### Fixed
- **Dragging cards in the Installed grid now reorders them.** Qt's own drag and
  drop treats a grid as free-floating icons, so drops didn't change the order (and
  on some setups lost the card). Sapphire now does the dragging itself in both
  views, with a marker showing where the mod will land, and it no longer depends
  on the desktop's drag and drop (which is flaky on some Wayland setups).
- **Searching Browse keeps your filters.** A search now stays inside the chosen
  category or hero and follows the sort order, instead of searching everything.
  The "Only my favourites" view also respects the category and sort.
- Identifying a hand-added mod kept its name but moved it to the bottom of the
  load order; it now keeps its place.

### Changed
- Every mod shows its load-order number, including mods that are off (dimmed), so
  the numbers don't jump around when you switch mods on and off.

## 1.6.0 — 2026-10-24

### Added
- **Crosshair editor** (new Crosshair page). Every crosshair setting Deadlock
  saves (colour, line thickness/length/gap/opacity, outlines and outline colour,
  the centre dot) with a live preview over different backgrounds. "Use in
  Deadlock" writes it into the game's settings and the Steam Cloud copy, after
  saving your current crosshair so "Restore my old crosshair" puts it back
  exactly. Save crosshairs by name, and copy/paste them as console commands
  (works with Deadlock Mod Manager share codes too). Deadlock must be closed.
- **autoexec.cfg editor** (Crosshair page → Autoexec), with the launch option it
  needs (`+exec autoexec`) one click away. It never saves an empty file, which
  can crash the game.
- **Flatpak package.** Every push builds `Sapphire.flatpak` on GitHub (tagged
  releases get it attached). Inside the Flatpak, Sapphire asks Steam whether
  Deadlock is running (it can't see other processes), the background helper's
  login entry goes in your real autostart folder, and updates point you to the
  newest bundle.
- **`sapphire --selftest`** checks an install works (Qt, sound previews decoding
  MP3, 7-Zip, the main window) without touching your mods. The Flatpak build
  runs it inside the sandbox before publishing the bundle.

### Changed
- Sapphire now installs PySide6-Essentials and PySide6-Addons instead of the
  whole PySide6 bundle, skipping Qt WebEngine and PDF it never used (a much
  smaller first install).
- The updater offers whichever is newer, the latest GitHub release or the
  version on main, so tagging releases doesn't hide fixes pushed in between.

## 1.5.0 — 2026-10-24

### Added
- **Sound previews.** Sound mods with a preview on GameBanana get a ▶ Preview
  button in Browse and on the Installed page, and a "♪ preview" badge on their
  card. Clips play inside Sapphire.
- **Favourites.** ☆ Favourite in a mod's details saves it; "Only my favourites"
  under Show lists them (works offline). Starred cards get a ★ badge.
- **Install a GameBanana collection.** Paste a collection link into "Install from
  a link": Sapphire lists its Deadlock mods (ones you already have are marked),
  you tick what you want, and it installs them.
- **Share a profile as a file.** Profiles → "Share as a file…" saves the profile
  (mods, order, on/off, chosen variants). "Import a profile file…" on the other
  computer downloads every GameBanana mod it doesn't have yet, then offers to
  switch to it. Mods added from files are listed so you know to send those too.
- **Roll back an update.** Updating a mod (or switching it to another file) now
  keeps the previous version. "Roll back" in its details swaps back, and rolling
  back again goes forward. Automatic updates leave a rolled-back mod alone.
- **Install mod updates automatically** (Settings → Behaviour, off by default).
- **One skin per hero** (Settings → Behaviour, off by default). Turning a skin on
  turns the other skins for that hero off. Skins are matched to heroes by the
  models they replace, so it works for mods added from files too. Each skin's
  details list the hero's other skins with a "Use this one" button whichever way
  the setting is.
- **Background helper** (Settings → Behaviour, off by default). A tiny helper
  starts when you log in and puts the mod folders back into gameinfo.gi after a
  Deadlock update even if Sapphire is closed, so launching from Steam still
  loads your mods. It does nothing while Sapphire is open.

### Fixed
- A missing or half-installed PipeWire can't crash Sapphire when playing a
  preview: Sapphire picks PulseAudio (which pipewire-pulse provides on Ubuntu and
  Bazzite) or ALSA itself.

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
