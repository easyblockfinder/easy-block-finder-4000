"""Manual donation addresses — not wired into mining."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DonateOption:
    id: str
    label: str
    network_note: str
    address: str
    qr_payload: str


DONATE_OPTIONS: tuple[DonateOption, ...] = (
    DonateOption(
        id="btc",
        label="Bitcoin (BTC)",
        network_note="Bitcoin network · bech32",
        address="bc1q4t3ax0xj8lpv6t8vhnv3x0jmth723x7l86rsak",
        qr_payload="bc1q4t3ax0xj8lpv6t8vhnv3x0jmth723x7l86rsak",
    ),
    DonateOption(
        id="bch",
        label="Bitcoin Cash (BCH)",
        network_note="Bitcoin Cash · CashAddr",
        address="qpsclskpllcnx8czg7z4d53z6xmnr950fgh2t27x78",
        qr_payload="bitcoincash:qpsclskpllcnx8czg7z4d53z6xmnr950fgh2t27x78",
    ),
    DonateOption(
        id="bnb",
        label="BNB (BSC)",
        network_note="BNB Smart Chain (BEP-20)",
        address="0xc2C8D324Bdb33CEbC7f8381A027F8042366544ac",
        qr_payload="0xc2C8D324Bdb33CEbC7f8381A027F8042366544ac",
    ),
    DonateOption(
        id="sol",
        label="Solana (SOL)",
        network_note="Solana network",
        address="D6vAYf23rap7p7LYQ4tQA9m9zZRomsMW4dg54E4bD9gt",
        qr_payload="D6vAYf23rap7p7LYQ4tQA9m9zZRomsMW4dg54E4bD9gt",
    ),
    DonateOption(
        id="usdt_trc20",
        label="Tether USDT (TRC-20)",
        network_note="Tron network · USDT-TRC20 only",
        address="TWREQJ5sovhwDCLfYDY5DGT79bGjHm3Guy",
        qr_payload="TWREQJ5sovhwDCLfYDY5DGT79bGjHm3Guy",
    ),
)


def get_donate_option(option_id: str) -> DonateOption | None:
    for opt in DONATE_OPTIONS:
        if opt.id == option_id:
            return opt
    return None
