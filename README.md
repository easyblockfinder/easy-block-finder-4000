![Easy Block Finder 4000](assets/ebf4000_logo.png)

# Easy Block Finder 4000

### Every Hash Is a Chance.

**Website:** [easyblockfinder.com](https://easyblockfinder.com)  
**[Download for Windows](https://github.com/easyblockfinder/easy-block-finder-4000/releases/latest)**

First time with the ready Windows package (verified on a clean Windows PC):

1. Download **`EBF4000-v*-windows.zip`** from the link above, then **extract** the zip to a normal folder (Desktop or Documents — do not run from inside WinRAR/7-Zip).
2. Double-click **`start.bat`**. If Python is missing, accept the offered auto-install (PATH is enabled for you). Wait until the app window opens.
3. Choose a network, enter your payout address, then press **Start**. Miners (XMRig/Rigel) download only after in-app consent.

**Free & Open-Source Solo Mining Software** (EBF4000 - v1.0.7)

Easy Block Finder 4000 is an independent, open-source **solo mining** app for Windows (BTC, BCH, XMR, RVN, ERG).  
It is not a simulation. **No earnings or hashrate are guaranteed.**

**Accepted share ≠ payout.** Rewards appear only after a block is accepted by the network / pool.

## Features

- One network at a time (full stop required before switching)
- **BTC / BCH:** native OpenCL SHA-256d (no CUDA Toolkit)
- **XMR:** managed XMRig (CPU / RandomX)
- **RVN / ERG:** managed Rigel (NVIDIA CUDA; KawPoW / Autolykos2)
- Manual **Donate** (QR + copy) — does **not** redirect mining hashrate to the author
- Thermal guard (Start blocked if temperature is unreadable, unless you opt in)
- Single-instance UI + system tray
- External miners are **not** in the zip; download only after consent, SHA-256 pinned
- Optional GitHub auto-update (signed ZIP; **Help → Check for Updates…**)

## How to use

In the app: **Help → How to Use…** (temperature limits, addresses, intensity, Start/Stop).  
Feedback: **Help → Feedback / Suggestions…** (`sametkuzu82@gmail.com`).

## Setup (Windows)

**Ready package:** use [Download for Windows](https://github.com/easyblockfinder/easy-block-finder-4000/releases/latest) and the three steps at the top of this README.

**From source** (after cloning this repo):

```bat
start.bat
```

Data folder: `%LOCALAPPDATA%\EasyBlockFinder4000`  
(legacy `SoloBlockStrike` / `BTCHunter` settings migrate once)

## Hardware Compatibility

| Cryptocurrency | NVIDIA | AMD | Intel |
|---|---|---|---|
| Bitcoin (BTC) | OpenCL | OpenCL (driver) | OpenCL (driver) |
| Bitcoin Cash (BCH) | OpenCL | OpenCL (driver) | OpenCL (driver) |
| Monero (XMR) | — (CPU via XMRig) | — (CPU via XMRig) | — (CPU via XMRig) |
| Ravencoin (RVN) | Rigel / CUDA | Not yet | Not yet |
| Ergo (ERG) | Rigel / CUDA | Not yet | Not yet |

Support depends on installed drivers and free VRAM (RVN/ERG). Without a usable GPU/OpenCL path, native BTC/BCH **fail explicitly** (no silent CPU fallback).

## Third-party miners (XMRig / Rigel)

EBF4000 does **not** ship miner binaries.

When you **Start** XMR, RVN, or ERG (or on first launch if engines are missing), the app asks for consent, then downloads **only** the selected official engine into AppData and verifies SHA-256 from `third_party/miners.lock.json`. Miners never run until you press Start. Windows Defender is never disabled by this app.

Upstream engines have their own licenses and developer fees — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Windows Security (do not disable Defender)

XMRig/Rigel may be flagged as CoinMiner (false positive). Keep Defender on. Exclude only  
`%LOCALAPPDATA%\EasyBlockFinder4000\miners`, restore the file from Protection history, then Start again.  
The app can open Windows Security or run `scripts\add_defender_exclusion.ps1` (UAC).

## Important Disclaimer

Full text: **[DISCLAIMER.md](DISCLAIMER.md)**. Easy Block Finder 4000 is experimental software.

- **Rewards:** Solo mining is probability-based; consumer hardware may never find a block.
- **Antivirus:** Mining tools are often flagged. Do **not** treat every alert as a false positive; verify the source and code before allowing exceptions.
- **Hardware / power:** Sustained CPU/GPU load and electricity use are your responsibility; monitor temperatures.
- **Temperature unreadable:** If the app cannot read CPU/GPU temperature, the automatic thermal guard **does not run**. Mining in that state can overheat or damage hardware. Start is blocked unless you explicitly accept the on-screen liability notice. Authors are **not liable** for damage, data loss, or other consequences of continuing without a temp guard. See [DISCLAIMER.md](DISCLAIMER.md).
- **Authorization:** Use only on hardware you own or are explicitly allowed to operate.

## Developers

From a source checkout:

```powershell
$env:PYTHONPATH="src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -q
```

Signed update packages: see [RELEASE_SIGNING.md](RELEASE_SIGNING.md).  
Latest Windows ZIP: [Releases](https://github.com/easyblockfinder/easy-block-finder-4000/releases/latest).

## License & trademarks

- Code: [Apache License 2.0](LICENSE)
- Disclaimer: [DISCLAIMER.md](DISCLAIMER.md)
- Name / logo / brand: reserved — see [TRADEMARKS.md](TRADEMARKS.md)
- Security notes: [SECURITY.md](SECURITY.md)
- Donations: [DONATE.md](DONATE.md)

## Support & governance

Voluntary donations support independent development ([DONATE.md](DONATE.md)).  
Official releases are published only by authorized maintainers. Community feedback is welcome.

---

**Easy Block Finder 4000 — Every Hash Is a Chance.**
