import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pypdf import PdfReader

from docsuite_engine.rpc import EngineError, call


@pytest.fixture()
def certificate(tmp_path):
    """A self-signed certificate + key in a password-protected PKCS#12 file."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ada Lovelace"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Org")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ada.p12"
    path.write_bytes(pkcs12.serialize_key_and_certificates(b"ada", key, cert, None, serialization.BestAvailableEncryption(b"s3cret")))
    return path


def test_sign_and_verify(sample_pdf, certificate, tmp_path):
    assert call("pdf.signatures", {"input": str(sample_pdf)})["signatures"] == []

    signed = tmp_path / "signed.pdf"
    result = call("pdf.sign", {
        "input": str(sample_pdf), "output": str(signed), "certificate": str(certificate), "passphrase": "s3cret",
        "reason": "Approved", "location": "Hyderabad", "visible": True, "page": 2,
    })
    assert result["signer"] == "Ada Lovelace" and result["visible"] is True and result["trusted_timestamp"] is False

    # The original bytes are kept verbatim; the signature is an appended revision.
    assert signed.read_bytes().startswith(sample_pdf.read_bytes().rstrip(b"\r\n"))
    assert len(PdfReader(str(signed)).pages) == 3
    info = call("pdf.signatures", {"input": str(signed)})
    assert info["trust_checked"] is False
    (sig,) = info["signatures"]
    assert sig["signer"] == "Ada Lovelace" and sig["intact"] is True and sig["valid"] is True
    assert sig["ok"] is True
    assert sig["covers_whole_file"] is True and sig["reason"] == "Approved" and sig["location"] == "Hyderabad"
    assert sig["signed_at"] is not None

    # A second signature keeps the first one valid, but the first no longer covers the whole file.
    twice = tmp_path / "twice.pdf"
    call("pdf.sign", {"input": str(signed), "output": str(twice), "certificate": str(certificate), "passphrase": "s3cret"})
    first, second = call("pdf.signatures", {"input": str(twice)})["signatures"]
    assert first["intact"] and first["valid"] and not first["covers_whole_file"]
    assert second["intact"] and second["valid"] and second["covers_whole_file"] and second["field"] == "Signature2"


def test_tampering_is_detected(sample_pdf, certificate, tmp_path):
    signed = tmp_path / "signed.pdf"
    call("pdf.sign", {"input": str(sample_pdf), "output": str(signed), "certificate": str(certificate), "passphrase": "s3cret"})
    data = bytearray(signed.read_bytes())
    at = data.index(b"Quarterly") if b"Quarterly" in data else data.index(b"/Producer") + 12
    data[at] ^= 0x01                                   # change one byte inside the signed range
    tampered = tmp_path / "tampered.pdf"
    tampered.write_bytes(bytes(data))
    (sig,) = call("pdf.signatures", {"input": str(tampered)})["signatures"]
    assert sig["intact"] is False and sig["ok"] is False       # the document no longer matches what was signed

    # Editing a signed PDF rewrites it, so the result carries no signature at all.
    edited = tmp_path / "edited.pdf"
    call("pdf.apply_edits", {"input": str(signed), "output": str(edited), "pages": [{"source": 0}]})
    assert call("pdf.signatures", {"input": str(edited)})["signatures"] == []


def test_sign_errors_leave_no_file(sample_pdf, certificate, tmp_path):
    out = tmp_path / "out.pdf"
    base = {"input": str(sample_pdf), "output": str(out), "certificate": str(certificate)}
    with pytest.raises(EngineError) as err:
        call("pdf.sign", {**base, "passphrase": "wrong"})
    assert err.value.code == "bad_certificate"
    junk = tmp_path / "junk.p12"
    junk.write_bytes(b"not a certificate")
    with pytest.raises(EngineError) as err:
        call("pdf.sign", {**base, "certificate": str(junk), "passphrase": "s3cret"})
    assert err.value.code == "bad_certificate"
    with pytest.raises(EngineError):
        call("pdf.sign", {**base, "passphrase": "s3cret", "visible": True, "page": 9})
    with pytest.raises(EngineError):
        call("pdf.sign", {**base, "output": str(sample_pdf), "passphrase": "s3cret"})
    assert not out.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["ada.p12", "junk.p12", "logo.png", "sample.pdf"]
