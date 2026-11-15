# SimpleFortChest 🏴‍☠️

A Windows desktop chest counter for Fortnite's Treasure Hunters event.

## Features

- **Global hotkey** (F8 by default): counts a chest even while Fortnite is focused.
- **Persistent ledger**: saves automatically to `%LOCALAPPDATA%\\SimpleFortChest\\chests.json` and restores it on launch.
- **Manual editing**: set your total chest count whenever you need to correct it.
- **Backup documents**: import and export your own JSON ledger.
- **Treasure Hour modes**: normal, 1.5× and a manually selected 2× announced session.
- **Probability dashboard**: next-chest odds, cumulative odds, squad estimate and reward-rate reference.
- **Pirate captain's log** interface, fully in Spanish.

## Run from source

1. Install Python 3.12 or newer.
2. Install dependencies: `py -m pip install -r requirements.txt`
3. Start the app: `py app.py`

On Windows, the global hotkey uses `pynput`. If Windows blocks keyboard hooks, check your security software and run the app normally (administrator privileges should not usually be necessary).

## Build

GitHub Actions builds a standalone Windows x64 executable. Push a tag such as `v1.0.0` to publish a GitHub Release, or run the workflow manually to download a build artifact.

## Probability notes

Epic's published normal-match rate for Pirate Shop Access is **1 in 137,500 per chest**. Epic lists a 1.5× boost during Treasure Hours and has announced a specific 2× session. Boosts must be selected manually in the app; it does not guess the event schedule.

Each chest is modeled as an independent roll:

`chance(at least one) = 1 - (1 - p)^n`

A previous miss does not improve the next chest's odds. The squad estimate is only an estimate that assumes each member opens roughly the same number of chests and that the reported party-wide reward behavior applies.

## Sources

- [Epic Games Support — Treasure chest drop rates](https://www.epicgames.com/help/c-34254770/c-33726977/what-are-the-drop-rates-of-treasure-in-chests-in-fortnite-battle-royale-s-pirate-treasure-event-a14361627)
- [Fortnite Status on X — odds announcement, November 7, 2026](https://x.com/FortniteStatus/status/2119202610322227327)
- [VGC — Pirate Shop Access and Treasure Hour details](https://www.videogameschronicle.com/news/fortnite-officially-confirms-pirate-shop-access-token-drop-rate-as-players-hunt-for-item-which-makes-entire-shop-free/)

Unofficial fan-made utility. Not affiliated with, endorsed by, or sponsored by Epic Games or Fortnite. No Epic account connection, game modification, memory reading, or automation is used.
