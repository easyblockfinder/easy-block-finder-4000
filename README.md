![Easy Block Finder 4000](assets/ebf4000_logo.png)

# Easy Block Finder 4000

### Every Hash Is a Chance.

**Free & Open-Source Solo Mining Software** (EBF4000 - v1.0)

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

## Setup (Windows)

```bat
start.bat
```

```powershell
$env:PYTHONPATH="src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -q
```

Data folder: `%LOCALAPPDATA%\EasyBlockFinder4000`  
(legacy `SoloBlockStrike` / `BTCHunter` settings migrate once)

## Hardware Compatibility

| Cryptocurrency | NVIDIA | AMD | Intel |
|---|---|---|---|
| Bitcoin (BTC) | OpenCL | OpenCL (driver) | OpenCL (driver) |
| Bitcoin Cash (BCH) | OpenCL | OpenCL (driver) | OpenCL (driver) |
| Monero (XMR) | — (CPU via XMRig) | — (CPU via XMRig) | — (CPU via XMRig) |
| Ravencoin (RVN) | Rigel / CUDA | Not in v1.0 | Not in v1.0 |
| Ergo (ERG) | Rigel / CUDA | Not in v1.0 | Not in v1.0 |

Support depends on installed drivers and free VRAM (RVN/ERG). Without a usable GPU/OpenCL path, native BTC/BCH **fail explicitly** (no silent CPU fallback).

## Third-party miners (XMRig / Rigel)

EBF4000 does **not** ship miner binaries.

When you **Start** XMR, RVN, or ERG, the app asks for consent, then downloads **only** that network’s official engine into AppData and verifies SHA-256 from `third_party/miners.lock.json`. Miners never run until you press Start. Consent can be changed in Settings. Windows Defender is never disabled by this app.

Upstream engines have their own licenses and developer fees — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Important Disclaimer

Easy Block Finder 4000 is experimental software.

- **Rewards:** Solo mining is probability-based; consumer hardware may never find a block.
- **Antivirus:** Mining tools are often flagged. Do **not** treat every alert as a false positive; verify the source and code before allowing exceptions.
- **Hardware / power:** Sustained CPU/GPU load and electricity use are your responsibility; monitor temperatures.
- **Authorization:** Use only on hardware you own or are explicitly allowed to operate.

## Download

Source lives in this repository. Installable packages (when published) are under [Releases](https://github.com/easyblockfinder/easy-block-finder-4000/releases).

## License & trademarks

- Code: [Apache License 2.0](LICENSE)
- Name / logo / brand: reserved — see [TRADEMARKS.md](TRADEMARKS.md)
- Security notes: [SECURITY.md](SECURITY.md)
- Donations: [DONATE.md](DONATE.md)

## Support & governance

Voluntary donations support independent development ([DONATE.md](DONATE.md)).  
Official releases are published only by authorized maintainers. Community feedback is welcome.

---

**Easy Block Finder 4000 — Every Hash Is a Chance.**
