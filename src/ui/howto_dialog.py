"""In-app How to use guide (English)."""

from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_icon

HOWTO_HTML = """
<h2>How to use Easy Block Finder 4000</h2>
<p><b>Solo mining only.</b> An accepted share is <b>not</b> a payout. Rewards appear only if a
block is found and accepted by the network / pool. There is no earnings guarantee.</p>

<h3>1. First launch</h3>
<ol>
<li>Run <code>start.bat</code> (Python 3.10–3.12, 64-bit recommended). Tick
<b>Add python.exe to PATH</b> when installing Python.</li>
<li>If XMRig / Rigel are missing, you may be asked to allow an official download.
Only engines you select are fetched; they are SHA-256 verified. Antivirus is never disabled.</li>
<li>Every launch opens <b>Choose network</b> (does not auto-start mining or jump to the
last session). Press <b>Start</b> only when you want hashing to begin.</li>
<li>Optional: <b>Check hardware / GPU capacity…</b> on that screen.
Use <b>File → Exit</b> (or tray <b>Exit</b>) to stop mining and external miners before exit.</li>
</ol>

<h3>2. Hardware detection &amp; capacity (optional)</h3>
<ol>
<li>From the network list, open the optional check to see <b>CPU</b> / <b>GPU</b>
<b>DETECTED</b> / <b>NOT DETECTED</b> (OpenCL for BTC/BCH, NVIDIA CUDA for RVN/ERG).</li>
<li>If a GPU is missing, related networks can be disabled with a reason.</li>
<li>Capacity check estimates <b>free VRAM</b> for KawPoW (RVN) and Autolykos2 (ERG).
Coins that do not fit are disabled (hover the red line for full detail).</li>
</ol>

<h3>3. Choose a network</h3>
<table border="0" cellspacing="4">
<tr><td><b>BTC</b></td><td>Bitcoin — GPU OpenCL (SHA-256d), CKPool solo</td></tr>
<tr><td><b>BCH</b></td><td>Bitcoin Cash — GPU OpenCL, CashAddr payout</td></tr>
<tr><td><b>XMR</b></td><td>Monero — CPU via XMRig (RandomX)</td></tr>
<tr><td><b>RVN / ERG</b></td><td>Ravencoin / Ergo — NVIDIA GPU via Rigel</td></tr>
</table>
<p>Only one network runs at a time. Stop mining before switching networks.</p>

<h3>4. Payout address (what to type)</h3>
<p>Enter the wallet address for the <b>selected network only</b>. Addresses are saved per network.</p>
<ul>
<li><b>BTC:</b> a standard Bitcoin address you control (legacy / SegWit / Bech32 as accepted by the pool).</li>
<li><b>BCH:</b> Bitcoin Cash CashAddr (with or without <code>bitcoincash:</code> prefix).</li>
<li><b>XMR:</b> a Monero primary address (not an integrated/subaddress unless your pool documents it).</li>
<li><b>RVN / ERG:</b> the matching coin address for that network.</li>
</ul>
<p>Wrong coin / wrong network address can mean lost funds. Double-check before Start.</p>

<h3>5. Intensity</h3>
<ul>
<li>Range: <b>1–10</b> (default <b>1</b>).</li>
<li>Higher values push the GPU/CPU harder (more heat and power). Start low; raise only if temperatures stay safe.</li>
</ul>

<h3>6. Temperature limits (Pause at / Resume at)</h3>
<p>These control the automatic thermal guard when a temperature reading is available.</p>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>Setting</th><th>UI range</th><th>Default</th><th>Recommended</th></tr>
<tr>
  <td><b>Pause at</b> (°C)</td>
  <td>50–95</td>
  <td>80</td>
  <td>GPU: <b>75–85</b> · CPU: <b>80–90</b><br/>
  Mining pauses when temperature reaches this value.</td>
</tr>
<tr>
  <td><b>Resume at</b> (°C)</td>
  <td>40–90</td>
  <td>70</td>
  <td>Keep <b>at least 5–10 °C below</b> Pause at<br/>
  (e.g. Pause 80 → Resume 70). Mining resumes only after cooling.</td>
</tr>
</table>
<p><b>Rules of thumb</b></p>
<ul>
<li><b>Resume at</b> must stay below <b>Pause at</b>. If they are too close, mining may flap on/off.</li>
<li>Do not set Pause near the absolute maximum your hardware can survive; leave headroom.</li>
<li>Laptop / small cases: prefer lower Pause (e.g. 70–75 °C) and good airflow.</li>
<li>If temperature <b>cannot be read</b>, the guard does not run. Start is blocked unless you
accept the on-screen liability notice. See DISCLAIMER.md.</li>
</ul>

<h3>7. CPU threads (XMR only)</h3>
<ul>
<li><b>0 = auto</b> (recommended for most users).</li>
<li>Or set a manual limit (1 … number of logical CPUs). Lower values reduce heat and leave
CPU free for the desktop.</li>
<li><b>Stop XMR mining on battery</b> — leave enabled on laptops.</li>
</ul>

<h3>8. Test mode</h3>
<p>When checked, the app does not use the real pool / real submit path for testing UI and
local behaviour. Turn it <b>off</b> for real solo mining.</p>

<h3>9. GPU pick (multi-GPU)</h3>
<p>For GPU networks, use <b>Pick GPU (bus/UUID)</b> if you have more than one card so thermal
monitoring and the miner target the same device.</p>

<h3>10. Start / Stop</h3>
<ol>
<li>Confirm network, address, and temperature settings.</li>
<li>Press <b>Start</b>. Missing XMRig/Rigel downloads only after your consent, with a progress window.</li>
<li>Watch Status: connection, hash rate, temperature, shares, event log.</li>
<li>Press <b>Stop</b> before quitting, changing network, or updating the app.</li>
</ol>

<h3>11. Shares, blocks, and fees</h3>
<ul>
<li><b>Accepted share</b> ≠ payout. It only means the pool accepted work.</li>
<li>A <b>block candidate</b> still needs network acceptance before any reward.</li>
<li>Pool / upstream engine fees (e.g. XMRig or Rigel developer fee) are separate and are
not added to your accepted-share count. This app does not redirect hashrate to donations —
use <b>Donate</b> if you want to support development.</li>
</ul>

<h3>12. Feedback</h3>
<ul>
<li><b>Help → Feedback / Suggestions…</b> (also in the tray menu).</li>
<li>Contact: <code>sametkuzu82@gmail.com</code> — Copy, or open Gmail / Outlook / Yahoo / default mail app with the address filled in.</li>
</ul>

<h3>13. Updates &amp; security</h3>
<ul>
<li><b>Help → Check for Updates…</b> — optional signed GitHub ZIP updates (your approval required).</li>
<li>Do not disable Windows Defender. For miner false positives, exclude only
<code>%LOCALAPPDATA%\\EasyBlockFinder4000\\miners</code> if you choose to.</li>
</ul>

<h3>14. Common messages (is this normal?)</h3>
<p>These status lines and dialogs are expected in many setups. The app keeps running unless
Start was blocked for a safety reason.</p>

<h4>Updates — “Could not check for updates” / GitHub HTTP 404</h4>
<ul>
<li><b>Normal</b> when the GitHub repo has <b>no published Release yet</b>
(<code>/releases/latest</code> returns Not Found).</li>
<li>The app continues normally. After an official signed Release is published
(<code>EBF4000-v…-windows.zip</code> + <code>SHA256SUMS</code> + <code>.minisig</code>),
checks succeed.</li>
<li>Network / rate-limit errors are also non-fatal; mining is unaffected.</li>
</ul>

<h4>Status — <code>suggest_difficulty response ignored … Unknown method</code></h4>
<ul>
<li><b>Normal on BCH (2Miners) and some other pools.</b></li>
<li>The client may send <code>mining.suggest_difficulty</code> (useful on CKPool/BTC).
Pools that do not implement it reply with error 20 “Unknown method”.</li>
<li>The response is ignored on purpose. Hashing and submits continue.</li>
</ul>

<h4>Pool page — “home page does not list you” / <code>/search</code></h4>
<ul>
<li>For 2Miners BCH use the <b>/account/bitcoincash:…</b> URL (shown in the UI), not only the pool home page.</li>
<li>Until the first <b>accepted share</b>, the site may show a search page or empty account —
this can take a while on consumer GPUs. Accepted share ≠ block / payout.</li>
</ul>

<h4>Network list — “insufficient VRAM” / hardware unavailable</h4>
<ul>
<li>RVN (KawPoW) and ERG (Autolykos2) need enough <b>free</b> NVIDIA VRAM for the current DAG/dataset.</li>
<li>A GTX 1650 with ~2–4 GB free will often be disabled while BTC/BCH/XMR stay available.</li>
<li>Close other GPU apps and use <b>Change network</b> → rescan if you freed VRAM.</li>
</ul>

<h4>Temperature unreadable — liability popup</h4>
<ul>
<li>If sensors cannot be read, automatic pause/resume does <b>not</b> run.</li>
<li>Start is blocked until you cancel or explicitly accept the on-screen disclaimer
(once or always). See also DISCLAIMER.md.</li>
</ul>

<h4>Windows Defender / “CoinMiner” on XMRig or Rigel</h4>
<ul>
<li>Common false positive for mining engines. Do <b>not</b> turn Defender off.</li>
<li>Exclude only <code>%LOCALAPPDATA%\\EasyBlockFinder4000\\miners</code> if you choose to,
restore the file from Protection history, then Start again. The app can open Windows Security
or the exclusion script (UAC) — it never bypasses antivirus.</li>
</ul>

<h4>Share difficulty / set_difficulty looks “easy”</h4>
<ul>
<li>Pool <code>mining.set_difficulty</code> is for share feedback only. A low share difficulty
does <b>not</b> improve real block-find odds on the coin network.</li>
</ul>

<h4>Miner download progress window</h4>
<ul>
<li>Official XMRig/Rigel ZIPs download only after consent; the progress dialog shows
download %, verify, and extract. Failures stay visible there (including Defender blocks).</li>
</ul>

<p style="color:#555;">Settings are stored under
<code>%LOCALAPPDATA%\\EasyBlockFinder4000</code> (wallets, options, downloaded miners).</p>
"""


class HowToUseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"How to use — {APP_NAME}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumSize(560, 520)
        self.resize(620, 640)

        root = QVBoxLayout(self)
        head = QLabel(f"{APP_NAME}  ·  {APP_VERSION_LABEL}")
        head.setFont(QFont("Bahnschrift", 12, QFont.Weight.DemiBold))
        root.addWidget(head)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(HOWTO_HTML)
        root.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)
