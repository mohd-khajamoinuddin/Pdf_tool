"""Certificate-based digital signatures for PDFs (pdf.sign / pdf.signatures).

Signing uses a local PKCS#12 file (.p12 / .pfx) and produces a PAdES-style
signature appended as an incremental update, so the signed bytes of the
original document are untouched.

Offline by construction: no timestamp authority is contacted and no revocation
data (OCSP / CRL) is fetched. Consequences the UI must be honest about:

* the signing time is this computer's clock, not a trusted timestamp;
* verification here checks integrity and the signature maths only. Whether the
  signer's certificate chains to an authority you trust, or has been revoked,
  is NOT checked - there is no trust store and no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..rpc import EngineError, method
from ..util import atomic_output, in_path

STAMP_W, STAMP_H, STAMP_MARGIN = 210.0, 62.0, 36.0


def _load_signer(certificate: Path, passphrase: Optional[str]):
    from pyhanko.sign import signers

    try:
        signer = signers.SimpleSigner.load_pkcs12(str(certificate), passphrase=(passphrase or "").encode("utf-8") or None)
    except Exception as exc:  # noqa: BLE001 - cryptography raises ValueError for a wrong passphrase
        raise EngineError("bad_certificate", "Could not open the certificate file. Check the file and its password.") from exc
    if signer is None:
        raise EngineError("bad_certificate", "Could not open the certificate file. Check the file and its password.")
    return signer


def _common_name(cert: Any) -> str:
    try:
        return cert.subject.native.get("common_name") or cert.subject.human_friendly
    except Exception:  # noqa: BLE001
        return "Unknown signer"


@method("pdf.sign")
def pdf_sign(params, ctx):
    """{input, output, certificate, passphrase?, reason?, location?, visible?: bool, page?: int, password?}"""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers

    path = in_path(params)
    certificate = in_path(params, "certificate")
    output = Path(str(params["output"]))
    if output.resolve() == path.resolve():
        raise EngineError("bad_params", "Output file must differ from the input file")
    signer = _load_signer(certificate, params.get("passphrase"))

    with open(path, "rb") as source:
        try:
            writer = IncrementalPdfFileWriter(source, strict=False)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("invalid_pdf", f"Could not read PDF: {exc}") from exc
        if writer.prev.encrypted:
            try:
                writer.encrypt(str(params.get("password") or ""))
            except Exception as exc:  # noqa: BLE001
                raise EngineError("password_required", "This PDF is password protected") from exc

        existing = len(list(writer.prev.embedded_signatures))
        field_name = f"Signature{existing + 1}"
        spec = None
        if params.get("visible"):
            page_count = int(writer.prev.root["/Pages"]["/Count"])
            page = int(params.get("page") or 0)
            if not 0 <= page < page_count:
                raise EngineError("bad_params", f"Page {page + 1} is out of range")
            box = (STAMP_MARGIN, STAMP_MARGIN, STAMP_MARGIN + STAMP_W, STAMP_MARGIN + STAMP_H)   # bottom-left corner
            spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=page, box=box)

        meta = signers.PdfSignatureMetadata(
            field_name=field_name,
            reason=str(params.get("reason") or "") or None,
            location=str(params.get("location") or "") or None,
        )
        ctx.progress(0.3, "signing")
        with atomic_output(output) as tmp, open(tmp, "wb") as target:
            try:
                signers.sign_pdf(writer, meta, signer=signer, new_field_spec=spec, output=target)
            except EngineError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise EngineError("sign_failed", f"Signing failed: {exc}") from exc

    return {
        "output": str(output),
        "signer": _common_name(signer.signing_cert),
        "field": field_name,
        "visible": bool(params.get("visible")),
        "trusted_timestamp": False,
    }


@method("pdf.signatures")
def pdf_signatures(params, ctx):
    """{input, password?} -> {signatures: [{field, signer, signed_at, ok, intact, valid, covers_whole_file, reason, location}]}

    `intact`  - the signed bytes have not changed since signing.
    `valid`   - the signature value verifies against the certificate embedded in it.
    `ok`      - both. This is the one to show: a tampered file is not intact but can still be "valid".
    None of them says the certificate itself is trustworthy; that is not checked offline.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    path = in_path(params)
    out: List[Dict[str, Any]] = []
    with open(path, "rb") as source:
        try:
            reader = PdfFileReader(source, strict=False)
            if reader.encrypted:
                reader.decrypt(str(params.get("password") or ""))
            embedded = list(reader.embedded_signatures)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("invalid_pdf", f"Could not read PDF: {exc}") from exc
        # No network, and no trust roots: the OS certificate store is deliberately not consulted,
        # so results are the same on every machine and never imply a trust decision.
        context = ValidationContext(allow_fetching=False, trust_roots=[])
        for sig in embedded:
            entry: Dict[str, Any] = {"field": sig.field_name, "signer": "Unknown signer", "signed_at": None,
                                     "intact": False, "valid": False, "ok": False, "covers_whole_file": False,
                                     "reason": None, "location": None}
            try:
                entry["signer"] = _common_name(sig.signer_cert)
                obj = sig.sig_object
                entry["reason"] = str(obj.get("/Reason")) if obj.get("/Reason") is not None else None
                entry["location"] = str(obj.get("/Location")) if obj.get("/Location") is not None else None
                status = validate_pdf_signature(sig, context, skip_diff=True)
                entry["intact"] = bool(status.intact)
                entry["valid"] = bool(status.valid)
                entry["ok"] = entry["intact"] and entry["valid"]
                entry["covers_whole_file"] = "ENTIRE_FILE" in str(status.coverage)
                if status.signer_reported_dt is not None:
                    entry["signed_at"] = status.signer_reported_dt.isoformat()
            except Exception as exc:  # noqa: BLE001 - a damaged signature is reported, not fatal
                entry["error"] = str(exc)[:200]
            out.append(entry)
    return {"signatures": out, "trust_checked": False}
