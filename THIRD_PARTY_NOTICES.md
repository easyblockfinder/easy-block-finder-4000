# Third-Party Software Notices

Easy Block Finder 4000 (EBF4000) is licensed under the **Apache License 2.0**.

That license covers **EBF4000’s own code** only. It does **not** relicense XMRig, Rigel, or other upstream miners.

## What is (and is not) in the package

Official EBF4000 archives **do not include** XMRig or Rigel binaries.

After you **consent** in the UI (or enable consent in Settings), EBF4000 may download **only the engine required for the network you Start** from the **official upstream GitHub release** URL pinned in `third_party/miners.lock.json`, then verify the archive with the pinned **SHA-256**.

- No download without consent  
- No silent install of unused miners  
- Engines do **not** run until you press **Start**  
- EBF4000 does **not** disable or bypass Windows Defender / antivirus  

## XMRig

| | |
|---|---|
| Website | https://xmrig.com |
| Source | https://github.com/xmrig/xmrig |
| License | **GNU GPL-3.0** |
| Used for | XMR (RandomX, CPU) |
| Upstream fee | Configurable donate level (default documented in `miners.lock.json`, typically ~1%) |

Any use, modification, or redistribution of XMRig must comply with GPL-3.0 (including source availability requirements for the XMRig software itself).

## Rigel Miner

| | |
|---|---|
| Website | https://rigelminer.com |
| Releases | https://github.com/rigelminer/rigel |
| License | **No OSI license file published upstream** — closed-source; subject to the publisher’s terms |
| Used for | RVN (KawPoW), ERG (Autolykos2); NVIDIA / CUDA |
| Upstream fee | Built-in developer fee (algorithm-dependent; see Rigel README, often ~1% for KawPoW / Autolykos2) |

An official download link does **not** grant EBF4000 (or you) rights to **redistribute** Rigel binaries inside EBF4000 release zips. EBF4000 only fetches the official build for the end user after consent.

## Independence

EBF4000 is not affiliated with, sponsored by, or endorsed by the XMRig or Rigel developers.

This notice does **not** grant any extra rights to copy or redistribute third-party software beyond what those projects’ own terms allow.
