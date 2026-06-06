"""Local RSA decryption of generated wallets' private keys.

When the API generates a wallet it returns the private key encrypted with the
RSA public key uploaded to your project (Project Settings -> RSA Key). The scheme
is RSA-OAEP / SHA-256 over base64-encoded ciphertext. Configure the matching
private key on the client to decrypt it locally.
"""

from __future__ import annotations

import base64
from typing import Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from .errors import CryptoChiefError


class RsaKeyNotConfiguredError(CryptoChiefError):
    """Raised by ``client.wallets.decrypt_private_key`` when no RSA key was configured."""

    def __init__(self) -> None:
        super().__init__(
            "cryptochief: RSA private key not configured - pass rsa_private_key to the client"
        )


def load_rsa_private_key_pem(pem: Union[str, bytes, bytearray]) -> RSAPrivateKey:
    """Parse a PEM-encoded RSA private key (PKCS#1 or PKCS#8) into a key object."""
    data = pem.encode("utf-8") if isinstance(pem, str) else bytes(pem)
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as err:  # noqa: BLE001 - normalize to our error type
        raise CryptoChiefError(f"cryptochief: RSA key: {err}") from err
    if not isinstance(key, RSAPrivateKey):
        raise CryptoChiefError("cryptochief: RSA key: not an RSA private key")
    return key


def load_rsa_private_key_file(path: str) -> RSAPrivateKey:
    """Read and parse a PEM-encoded RSA private key from disk."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as err:
        raise CryptoChiefError(f"cryptochief: read RSA key {path!r}: {err}") from err
    return load_rsa_private_key_pem(data)


def decrypt_rsa_oaep(key: RSAPrivateKey, base64_ciphertext: str) -> str:
    """Decrypt a single base64-encoded RSA-OAEP / SHA-256 payload.

    The exact encoding the API uses for ``private_key_encrypted``. Returns the
    wallet's raw private key in the chain's native hex form.
    """
    ciphertext = base64.b64decode(base64_ciphertext)
    try:
        plaintext = key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except Exception as err:  # noqa: BLE001 - normalize to our error type
        raise CryptoChiefError(f"cryptochief: RSA decrypt: {err}") from err
    return plaintext.decode("utf-8")
