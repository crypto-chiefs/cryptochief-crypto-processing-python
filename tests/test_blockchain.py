"""The two chain/asset catalogue endpoints and the wire shapes that surprise.

``/v1/blockchains/list`` answers with a **bare top-level array** where every
other list endpoint answers with an ``items`` envelope - a decoder written for
``{"items": [...]}`` type-checks fine and only fails against the real server.

``/v1/blockchain/contracts/list`` shares its row shape with
``/v1/blockchain/contracts/available``, including ``chain_family`` and
``is_test``, and reports a native coin's contract as an empty string rather than
``null``.
"""

import json

import httpx

from cryptochief import ChainFamily, CryptoChiefClient

CATALOGUE_RESPONSE = {
    "items": [
        {
            "network": "ETH_MAINNET",
            "coin": "ETH",
            "contract": "",
            "chain_family": "EVM",
            "type": "native",
            "is_test": False,
            "decimals": 18,
        },
        {
            "network": "TRON_MAINNET",
            "coin": "USDT",
            "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "chain_family": "TRON",
            "type": "token",
            "is_test": False,
            "decimals": 6,
        },
        {
            "network": "SOLANA_DEVNET",
            "coin": "SOL",
            "contract": "",
            "chain_family": "SOLANA",
            "type": "native",
            "is_test": True,
            "decimals": 9,
        },
    ]
}


def _client(captured: dict, payload) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload)

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _raw_client(captured: dict, raw: bytes) -> CryptoChiefClient:
    """A client answering with ``raw`` bytes verbatim.

    ``httpx.Response(json=None)`` sends an *empty* body, not the four bytes
    ``null``, so the null-body cases have to hand over the bytes themselves.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _body(captured: dict) -> dict:
    return json.loads(captured["request"].content.decode())


async def test_supported_chains_decodes_a_bare_top_level_array():
    captured: dict = {}
    # Not {"items": [...]} - the server sends the array itself. A model built
    # around an envelope compiles and then finds nothing at runtime.
    client = _client(
        captured,
        [
            {"name": "ETH_MAINNET", "type": "evm"},
            {"name": "ETH_SEPOLIA", "type": "evm"},
            {"name": "TRON_MAINNET", "type": "tron"},
            {"name": "SOLANA_MAINNET", "type": "solana"},
        ],
    )

    chains = await client.blockchain.supported_chains()

    assert str(captured["request"].url).endswith("/v1/blockchains/list")
    # Signed like every other request, with an empty object for a body.
    assert _body(captured) == {}
    assert len(chains) == 4
    assert chains[0].name == "ETH_MAINNET"
    # The scanner's own lowercase vocabulary, not the uppercase ChainFamily the
    # chain_family fields carry.
    assert chains[0].type == "evm"
    assert chains[2].name == "TRON_MAINNET"
    assert chains[2].type == "tron"
    assert [c.name for c in chains] == [
        "ETH_MAINNET",
        "ETH_SEPOLIA",
        "TRON_MAINNET",
        "SOLANA_MAINNET",
    ]


async def test_supported_chains_on_an_empty_array():
    captured: dict = {}
    client = _client(captured, [])

    assert await client.blockchain.supported_chains() == []


async def test_supported_chains_on_a_literal_null_body():
    captured: dict = {}
    # The service builds its answer from a nil slice, so an empty catalogue
    # marshals as JSON `null` rather than `[]`. A method promising a list has to
    # hand back an empty one: not None, not an exception, not a decode error.
    client = _raw_client(captured, b"null")

    chains = await client.blockchain.supported_chains()

    assert chains == []
    assert isinstance(chains, list)
    # Safe to iterate without a None guard, which is the whole point.
    assert [c.name for c in chains] == []


async def test_contracts_list_keeps_chain_family_and_is_test():
    captured: dict = {}
    client = _client(captured, CATALOGUE_RESPONSE)

    out = await client.blockchain.contracts_list()

    assert str(captured["request"].url).endswith("/v1/blockchain/contracts/list")
    # Platform-wide: there is nothing to filter by project.
    assert _body(captured) == {}
    assert out.items is not None
    eth, usdt, sol = out.items

    assert eth.chain_family == ChainFamily.EVM.value
    assert usdt.chain_family == ChainFamily.TRON.value
    # is_test is the only thing telling a real asset from a test one, and it
    # travels on both asset endpoints.
    assert eth.is_test is False
    assert sol.is_test is True
    assert usdt.decimals == 6


async def test_contracts_list_reports_a_native_coin_as_an_empty_contract():
    captured: dict = {}
    client = _client(captured, CATALOGUE_RESPONSE)

    out = await client.blockchain.contracts_list()

    assert out.items is not None
    eth, usdt, _sol = out.items
    # An empty string, not None and not an error: "" is how the API says
    # "native coin", so `if row.contract:` is the test for "this is a token".
    assert eth.contract == ""
    assert eth.contract is not None
    assert eth.type == "native"
    assert usdt.contract == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    assert usdt.type == "token"


async def test_contracts_available_shares_the_row_type_with_the_catalogue():
    captured: dict = {}
    client = _client(
        captured,
        {
            "items": [
                {
                    "network": "ARBITRUM_SEPOLIA",
                    "coin": "ETH",
                    "contract": "",
                    "chain_family": "EVM",
                    "type": "native",
                    "is_test": True,
                    "decimals": 18,
                }
            ]
        },
    )

    out = await client.blockchain.contracts_available("ARBITRUM_SEPOLIA")

    assert str(captured["request"].url).endswith("/v1/blockchain/contracts/available")
    assert _body(captured) == {"network": "ARBITRUM_SEPOLIA"}
    assert out.items is not None
    # Same fields on this endpoint: one row type, not two.
    assert out.items[0].chain_family == "EVM"
    assert out.items[0].is_test is True
