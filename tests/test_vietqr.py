"""infra/vietqr.py — EMVCo TLV payload, CRC-16/CCITT-FALSE, UX helpers."""

import pytest

from infra import vietqr


# ------------------------------------------------------------------------ CRC


def test_crc16_reference_vector():
    # Standard CRC-16/CCITT-FALSE check value — the known-good reference:
    # poly 0x1021, init 0xFFFF, no reflect/xorout => CRC("123456789") = 0x29B1.
    assert vietqr.crc16_ccitt(b"123456789") == 0x29B1


def test_crc16_empty_is_init():
    assert vietqr.crc16_ccitt(b"") == 0xFFFF


def test_payload_crc_validates_and_tamper_detected():
    payload = vietqr.build_payload("VCB", "0071000123456", amount=51000, message="don nhom")
    assert vietqr.validate_crc(payload)
    tampered = payload[:-9] + ("9" if payload[-9] != "9" else "8") + payload[-8:]
    assert not vietqr.validate_crc(tampered)
    assert not vietqr.validate_crc("0002")  # too short / no 6304 trailer


# ---------------------------------------------------------------- TLV payload


def test_payload_field_order_and_values():
    payload = vietqr.build_payload("VCB", "0071000123456", amount=73000, message="TQ ord_abc")
    top = vietqr.parse_tlv(payload)
    # Field ORDER per NAPAS IBFT spec: 00, 01, 38, 53, 54, 58, 62, 63.
    assert list(top) == ["00", "01", "38", "53", "54", "58", "62", "63"]
    assert top["00"] == "01"
    assert top["01"] == "12"  # dynamic (amount present)
    assert top["53"] == "704"  # VND
    assert top["54"] == "73000"
    assert top["58"] == "VN"
    assert len(top["63"]) == 4  # CRC hex

    merchant = vietqr.parse_tlv(top["38"])
    assert list(merchant) == ["00", "01", "02"]
    assert merchant["00"] == "A000000727"  # NAPAS GUID
    assert merchant["02"] == "QRIBFTTA"    # transfer-to-account service
    beneficiary = vietqr.parse_tlv(merchant["01"])
    assert beneficiary["00"] == "970436"   # Vietcombank BIN
    assert beneficiary["01"] == "0071000123456"

    extra = vietqr.parse_tlv(top["62"])
    assert extra["08"] == "TQ ord_abc"


def test_static_payload_no_amount():
    payload = vietqr.build_payload("MB", "999888777")
    top = vietqr.parse_tlv(payload)
    assert top["01"] == "11"  # static QR
    assert "54" not in top and "62" not in top
    assert vietqr.validate_crc(payload)


def test_message_is_ascii_folded():
    payload = vietqr.build_payload("ACB", "123", amount=10000, message="Bình trả  Ăn trưa!")
    note = vietqr.parse_tlv(vietqr.parse_tlv(payload)["62"])["08"]
    assert note == "Binh tra An trua"
    assert note.isascii()


def test_bank_bin_accepts_code_name_or_raw_bin():
    assert vietqr.bank_bin("vcb") == "970436"
    assert vietqr.bank_bin("Vietcombank") == "970436"
    assert vietqr.bank_bin("970422") == "970422"  # literal BIN passes through
    with pytest.raises(vietqr.VietQRError):
        vietqr.bank_bin("NGAN_HANG_LA")


def test_bad_inputs_raise():
    with pytest.raises(vietqr.VietQRError):
        vietqr.build_payload("VCB", "")
    with pytest.raises(vietqr.VietQRError):
        vietqr.build_payload("VCB", "123", amount=-5)


# ------------------------------------------------------------- render + UX


def test_qr_png_renders_and_writes(tmp_path):
    payload = vietqr.build_payload("VCB", "0071000123456", amount=51000)
    out = tmp_path / "qr" / "pay.png"
    data = vietqr.qr_png(payload, out)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert out.is_file() and out.read_bytes() == data


def test_deep_link_and_copy_text():
    link = vietqr.deep_link("VCB", "0071000123456", amount=51000, message="tra tien com")
    assert link.startswith("https://dl.vietqr.io/pay?")
    assert "970436" in link and "am=51000" in link

    text = vietqr.copy_text("VCB", "0071000123456", account_name="TRAN THI BA",
                            amount=51000, message="trả tiền cơm")
    assert "Số TK: 0071000123456" in text
    assert "51.000đ" in text
    assert "tra tien com" in text  # folded


def test_group_split_payloads_fills_placeholders():
    split = {
        "An": {"amount": 35000, "is_payer": True},
        "Binh": {"amount": 51000, "is_payer": False,
                 "vietqr_placeholder": {"payee": "An", "amount": 51000,
                                        "note": "g_x Binh tra An", "bank": None, "account": None}},
    }
    conf = {"bank": "VCB", "account": "0071000123456"}
    payloads = vietqr.group_split_payloads(split, conf)
    assert set(payloads) == {"Binh"}
    assert vietqr.validate_crc(payloads["Binh"])
    assert vietqr.parse_tlv(payloads["Binh"])["54"] == "51000"
