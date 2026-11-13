"""Create sample.pdf, data.csv and picture.png in a folder, for manual testing and scripts/smoke.cjs.

    engine\\.venv\\Scripts\\python scripts\\make_samples.py <folder>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine" / "tests"))

import conftest  # noqa: E402

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
build = getattr(conftest.sample_pdf, "__wrapped__", None) or conftest.sample_pdf.__pytest_wrapped__.obj
build(folder)
(folder / "logo.png").unlink(missing_ok=True)
from PIL import Image, ImageDraw  # noqa: E402

picture = Image.new("RGB", (480, 270), (16, 42, 67))
draw = ImageDraw.Draw(picture)
draw.rectangle([40, 150, 140, 230], fill=(240, 180, 41))
draw.ellipse([200, 60, 320, 180], fill=(46, 111, 219))
draw.polygon([(380, 220), (440, 220), (410, 120)], fill=(18, 183, 106))
picture.save(folder / "picture.png")
(folder / "data.csv").write_text("region,q1,q2,total\nNorth,120,135,=B2+C2\nSouth,98,110,=B3+C3\n", encoding="utf-8")

# A throw-away self-signed certificate (password "test") for trying out PDF signing.
import datetime as dt  # noqa: E402

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sample Signer")])
now = dt.datetime.now(dt.timezone.utc)
cert = (
    x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
    .not_valid_after(now + dt.timedelta(days=30))
    .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
    .sign(key, hashes.SHA256())
)
(folder / "sample-signer.p12").write_bytes(
    pkcs12.serialize_key_and_certificates(b"sample", key, cert, None, serialization.BestAvailableEncryption(b"test"))
)
print("wrote", sorted(p.name for p in folder.iterdir()))
