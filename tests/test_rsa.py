import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cryptochief import (
    CryptoChiefClient,
    RsaKeyNotConfiguredError,
    decrypt_rsa_oaep,
    load_rsa_private_key_pem,
)


def _encrypt_for_project(public_key, plaintext: str) -> str:
    ct = public_key.encrypt(
        plaintext.encode("utf-8"),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return base64.b64encode(ct).decode("ascii")


def _pem(private_key, fmt) -> str:
    return private_key.private_bytes(
        serialization.Encoding.PEM, fmt, serialization.NoEncryption()
    ).decode("ascii")


@pytest.mark.parametrize(
    "fmt",
    [serialization.PrivateFormat.PKCS8, serialization.PrivateFormat.TraditionalOpenSSL],
)
def test_decrypt_module_functions(fmt):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    secret = "0xabc123deadbeefcafef00d"
    ciphertext = _encrypt_for_project(priv.public_key(), secret)
    key = load_rsa_private_key_pem(_pem(priv, fmt))
    assert decrypt_rsa_oaep(key, ciphertext) == secret


async def test_client_decrypt_private_key():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ciphertext = _encrypt_for_project(priv.public_key(), "hello-world")
    pem = _pem(priv, serialization.PrivateFormat.PKCS8)
    async with CryptoChiefClient(merchant_id="M", api_key="K", rsa_private_key=pem) as client:
        assert client.wallets.decrypt_private_key(ciphertext) == "hello-world"


async def test_raises_when_no_key_configured():
    async with CryptoChiefClient(merchant_id="M", api_key="K") as client:
        with pytest.raises(RsaKeyNotConfiguredError):
            client.wallets.decrypt_private_key("AA==")
