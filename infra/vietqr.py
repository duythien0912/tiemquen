"""VietQR payload (EMVCo MPM TLV, NAPAS IBFT-to-account) — ARCH §3.2.

Builds the EMVCo Merchant-Presented-Mode string a banking app scans to
prefill a transfer: NAPAS GUID `A000000727`, bank BIN + account nested in
field 38, service code `QRIBFTTA` (transfer to account), currency 704 (VND),
country VN, optional amount (dynamic QR) + message (field 62-08), CRC-16/
CCITT-FALSE trailer in field 63.

Tiền vào THẲNG tài khoản seller (hoặc người trả hộ đơn nhóm) — platform
không giữ tiền (ARCH §4.4/§4.6). Ngoài payload còn 2 helper cho UX ARCH §3.2
"khách không thể tự quét QR trên màn hình mình đang cầm":
`deep_link()` mở app ngân hàng, `copy_text()` = nút "copy số TK + số tiền".
"""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any


class VietQRError(ValueError):
    pass


# ------------------------------------------------------------------ bank BINs

#: NAPAS acquirer BINs for common banks (subset — extend as sellers onboard).
BANK_BINS: dict[str, str] = {
    "VCB": "970436", "VIETCOMBANK": "970436",
    "TCB": "970407", "TECHCOMBANK": "970407",
    "MB": "970422", "MBBANK": "970422",
    "ACB": "970416",
    "VIB": "970441",
    "BIDV": "970418",
    "VPB": "970432", "VPBANK": "970432",
    "TPB": "970423", "TPBANK": "970423",
    "STB": "970403", "SACOMBANK": "970403",
    "AGRIBANK": "970405", "AGR": "970405",
    "VTB": "970415", "VIETINBANK": "970415", "ICB": "970415",
}

_BIN_RE = re.compile(r"^\d{6}$")


def bank_bin(bank: str) -> str:
    """Resolve a bank code/name ('VCB', 'Vietcombank') or literal 6-digit BIN."""
    key = (bank or "").strip().upper()
    if _BIN_RE.match(key):
        return key
    if key in BANK_BINS:
        return BANK_BINS[key]
    raise VietQRError(f"không biết BIN của ngân hàng {bank!r} — truyền thẳng 6 số BIN NAPAS")


# ------------------------------------------------------------------- CRC + TLV


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflect, no xorout).

    Standard check value: crc16_ccitt(b"123456789") == 0x29B1 — the reference
    vector the unit tests pin (EMVCo QR spec Annex uses exactly this CRC).
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise VietQRError(f"TLV field {tag} quá dài ({len(value)} > 99): {value[:30]!r}...")
    return f"{tag}{len(value):02d}{value}"


def parse_tlv(payload: str) -> dict[str, str]:
    """Parse ONE level of TLV into {tag: value} (test/debug helper).
    Preserves insertion order (dict) so field ordering is assertable."""
    out: dict[str, str] = {}
    i = 0
    while i < len(payload):
        tag, ln = payload[i : i + 2], payload[i + 2 : i + 4]
        if len(ln) < 2 or not ln.isdigit():
            raise VietQRError(f"TLV hỏng tại offset {i}: {payload[i:i+8]!r}")
        n = int(ln)
        value = payload[i + 4 : i + 4 + n]
        if len(value) != n:
            raise VietQRError(f"TLV field {tag} khai {n} ký tự nhưng thiếu dữ liệu")
        out[tag] = value
        i += 4 + n
    return out


# -------------------------------------------------------------------- payload

_MESSAGE_KEEP_RE = re.compile(r"[^A-Za-z0-9 .,_-]+")


def _fold_message(message: str, max_len: int = 70) -> str:
    """ASCII-fold the transfer note — bank cores routinely mangle diacritics,
    and NAPAS field 62-08 is safest as plain ASCII."""
    s = message.strip().replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = _MESSAGE_KEEP_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()[:max_len]


def build_payload(
    bank: str, account: str, amount: int | None = None, message: str | None = None
) -> str:
    """EMVCo TLV VietQR string. `amount` in whole VND -> dynamic QR (01=12);
    no amount -> static QR (01=11). Field order per NAPAS IBFT spec:
    00, 01, 38 (GUID + BIN/account + QRIBFTTA), 53, [54], 58, [62], 63=CRC."""
    account = re.sub(r"\s+", "", str(account or ""))
    if not account:
        raise VietQRError("thiếu số tài khoản")

    beneficiary = _tlv("00", bank_bin(bank)) + _tlv("01", account)
    merchant_info = _tlv("00", "A000000727") + _tlv("01", beneficiary) + _tlv("02", "QRIBFTTA")

    parts = [
        _tlv("00", "01"),                              # payload format indicator
        _tlv("01", "12" if amount else "11"),          # dynamic if amount present
        _tlv("38", merchant_info),                     # NAPAS merchant account info
        _tlv("53", "704"),                             # currency VND
    ]
    if amount:
        amount = int(amount)
        if amount <= 0:
            raise VietQRError(f"số tiền phải > 0, nhận {amount}")
        parts.append(_tlv("54", str(amount)))
    parts.append(_tlv("58", "VN"))
    if message:
        folded = _fold_message(message)
        if folded:
            parts.append(_tlv("62", _tlv("08", folded)))

    body = "".join(parts) + "6304"                     # CRC covers "6304" itself
    return body + f"{crc16_ccitt(body.encode('ascii')):04X}"


def validate_crc(payload: str) -> bool:
    """True if the trailing field-63 CRC matches the payload it covers."""
    if len(payload) < 8 or payload[-8:-4] != "6304":
        return False
    expected = f"{crc16_ccitt(payload[:-4].encode('ascii')):04X}"
    return payload[-4:].upper() == expected


# --------------------------------------------------------------- render + UX


def qr_png(payload: str, path: str | Path | None = None) -> bytes:
    """Render the payload as a QR PNG. Writes to `path` if given; returns bytes."""
    import qrcode

    img = qrcode.make(payload, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return data


def deep_link(
    bank: str, account: str, amount: int | None = None, message: str | None = None
) -> str:
    """Bank-app deep link (dl.vietqr.io universal link — opens the picker on
    mobile). Fallback UX when the buyer can't scan their own screen."""
    from urllib.parse import quote

    url = f"https://dl.vietqr.io/pay?app=pick&ba={quote(str(account))}@{bank_bin(bank).lower()}"
    if amount:
        url += f"&am={int(amount)}"
    if message:
        url += f"&tn={quote(_fold_message(message))}"
    return url


def copy_text(
    bank: str,
    account: str,
    account_name: str | None = None,
    amount: int | None = None,
    message: str | None = None,
) -> str:
    """Nội dung nút 'copy số TK + số tiền' (ARCH §3.2) — paste thẳng vào app bank."""
    lines = [f"Ngân hàng: {bank}", f"Số TK: {account}"]
    if account_name:
        lines.append(f"Chủ TK: {account_name}")
    if amount:
        lines.append(f"Số tiền: {int(amount):,}đ".replace(",", "."))
    if message:
        lines.append(f"Nội dung: {_fold_message(message)}")
    return "\n".join(lines)


def group_split_payloads(split: dict[str, Any], vietqr_conf: dict[str, Any]) -> dict[str, str]:
    """Fill real payloads for a group-order split (infra/group_orders.py shapes
    `vietqr_placeholder`; this turns each non-payer entry into a scannable
    payload refunding the payer). `vietqr_conf` = {"bank", "account", ...}."""
    out: dict[str, str] = {}
    for name, entry in split.items():
        ph = entry.get("vietqr_placeholder")
        if not ph:
            continue
        out[name] = build_payload(
            vietqr_conf["bank"], vietqr_conf["account"],
            amount=ph["amount"], message=ph.get("note"),
        )
    return out


__all__ = [
    "BANK_BINS", "VietQRError", "bank_bin", "build_payload", "copy_text",
    "crc16_ccitt", "deep_link", "group_split_payloads", "parse_tlv",
    "qr_png", "validate_crc",
]
