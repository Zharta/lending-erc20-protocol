# ruff: noqa: ERA001

import os
import random
from collections import namedtuple
from datetime import datetime
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import NamedTuple

import ape
import boa
import eth_abi
import requests
import vyper
import web3
from ape import convert, networks
from eth_account import Account
from eth_account.messages import encode_typed_data
from hexbytes import HexBytes

from scripts.deployment import DeploymentManager, Environment

ENV = Environment[os.environ.get("ENV", "local")]
CHAIN = os.environ.get("CHAIN", "nochain")


ZERO_ADDRESS = "0x" + "0" * 40
ZERO_BYTES32 = b"\0" * 32
BPS = 10000
DAY = 24 * 3600
FAR_AWAY_IN_THE_FUTURE = 4911095666

URL_ENV_INFIX = f".{ENV.name}" if ENV != Environment.prod else ""  # noqa: SIM300 Yoda this condition is not
ERC20_SERVICE_BASE_URL = f"https://api{URL_ENV_INFIX}.zharta.io/loans-erc20/v1"
# ERC20_SERVICE_BASE_URL = f"http://localhost:8000/loans-erc20/v1"


class Context(Enum):
    DEPLOYMENT = "deployment"
    CONSOLE = "console"


dm = DeploymentManager(ENV, CHAIN, Context.CONSOLE)


def inject_poa(w3):
    w3.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
    return w3


def now():
    return int(datetime.now().timestamp())


def transfer(w3, wallet, val=10**60):
    b = w3.eth.coinbase
    w3.eth.send_transaction({"from": b, "to": wallet, "value": val})
    print(f"new balance: {w3.eth.get_balance(wallet)}")


def propose_owner(dm, from_wallet, to_wallet):
    contracts = [c for c in dm.context.contracts.values() if hasattr(c.contract, "proposeOwner")]
    dm.owner.set_autosign(True)
    for i, c in enumerate(contracts):
        c.contract.proposeOwner(to_wallet, sender=from_wallet, gas_price=convert("28 gwei", int))
        print(f"Signed contract {i + 1} out of {len(contracts)}")


def claim_ownership(dm, wallet):
    contracts = [c for c in dm.context.contracts.values() if hasattr(c.contract, "claimOwnership")]
    dm.owner.set_autosign(True)
    for i, c in enumerate(contracts):
        c.contract.claimOwnership(sender=wallet, gas_price=convert("28 gwei", int))
        print(f"Signed contract {i + 1} out of {len(contracts)}")


class Offer(NamedTuple):
    principal: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    collateral_token: str = ZERO_ADDRESS
    duration: int = 0
    origination_fee_bps: int = 0
    min_collateral_amount: int = 0
    max_iltv: int = 0
    available_liquidity: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    soft_liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    expiration: int = 0
    lender: str = ZERO_ADDRESS
    borrower: str = ZERO_ADDRESS
    tracing_id: bytes = random.randbytes(32)


Signature = namedtuple("Signature", ["v", "r", "s"], defaults=[0, ZERO_BYTES32, ZERO_BYTES32])

SignedOffer = namedtuple("SignedOffer", ["offer", "signature"], defaults=[Offer(), Signature()])

WalletValidation = namedtuple("WalletValidation", ["wallet", "expiration_time"], defaults=[ZERO_ADDRESS, 0])

SignedWalletValidation = namedtuple(
    "SignedWalletValidation", ["validation", "signature"], defaults=[WalletValidation(), Signature()]
)


class Loan(NamedTuple):
    id: bytes = ZERO_BYTES32
    offer_id: bytes = ZERO_BYTES32
    offer_tracing_id: bytes = ZERO_BYTES32
    initial_amount: int = 0
    amount: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    maturity: int = 0
    start_time: int = 0
    accrual_start_time: int = 0
    borrower: str = ZERO_ADDRESS
    lender: str = ZERO_ADDRESS
    collateral_token: str = ZERO_ADDRESS
    collateral_amount: int = 0
    min_collateral_amount: int = 0
    origination_fee_amount: int = 0
    protocol_upfront_fee_amount: int = 0
    protocol_settlement_fee: int = 0
    soft_liquidation_fee: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    soft_liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    initial_ltv: int = 0
    call_time: int = 0

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600 * BPS)


def compute_loan_hash(loan: Loan):
    print(f"compute_loan_hash {loan=}")
    encoded = eth_abi.encode(
        [
            "(bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256)"
        ],
        [loan],
    )
    return boa.eval(f"""keccak256({encoded})""")


def _compute_signed_offer_id(offer: SignedOffer):
    import boa  # noqa: PLC0415 temp workaround

    offer_id = boa.eval(
        dedent(f"""keccak256(concat(convert({offer.signature.v}, bytes32), {offer.signature.r}, {offer.signature.s}))""")
    )
    return HexBytes(offer_id).to_0x_hex()


SignedOffer.offer_id = property(_compute_signed_offer_id)


def sign_offer(offer: Offer, lender: Account, verifying_contract: str) -> SignedOffer:
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Offer": [
                {"name": "principal", "type": "uint256"},
                {"name": "apr", "type": "uint256"},
                {"name": "payment_token", "type": "address"},
                {"name": "collateral_token", "type": "address"},
                {"name": "duration", "type": "uint256"},
                {"name": "origination_fee_bps", "type": "uint256"},
                {"name": "min_collateral_amount", "type": "uint256"},
                {"name": "max_iltv", "type": "uint256"},
                {"name": "available_liquidity", "type": "uint256"},
                {"name": "call_eligibility", "type": "uint256"},
                {"name": "call_window", "type": "uint256"},
                {"name": "soft_liquidation_ltv", "type": "uint256"},
                {"name": "oracle_addr", "type": "address"},
                {"name": "expiration", "type": "uint256"},
                {"name": "lender", "type": "address"},
                {"name": "borrower", "type": "address"},
                {"name": "tracing_id", "type": "bytes32"},
            ],
        },
        "primaryType": "Offer",
        "domain": {
            "name": "Zharta",
            "version": "1",
            "chainId": networks.chain_manager.chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": offer._asdict(),
    }
    signable_msg = encode_typed_data(full_message=typed_data)
    signed_msg = lender.sign_message(signable_msg)
    lender_signature = Signature(signed_msg.v, signed_msg.r, signed_msg.s)
    return SignedOffer(offer, lender_signature)


def sign_kyc(wallet: str, signer: Account, verifying_contract: str, expiration: int = 0) -> SignedWalletValidation:
    expiration = expiration or now() + 30 * 24 * 3600
    wallet_validation = {"wallet": wallet, "expiration_time": expiration}
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "WalletValidation": [
                {"name": "wallet", "type": "address"},
                {"name": "expiration_time", "type": "uint256"},
            ],
        },
        "primaryType": "WalletValidation",
        "domain": {
            "name": "Zharta",
            "version": "1",
            "chainId": networks.chain_manager.chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": wallet_validation,
    }
    signable_msg = encode_typed_data(full_message=typed_data)
    signed_msg = signer.sign_message(signable_msg)

    signature = Signature(signed_msg.v, HexBytes(signed_msg.r), HexBytes(signed_msg.s))

    return SignedWalletValidation(WalletValidation(**wallet_validation), signature)


def get_offer(offer_id: str | HexBytes | bytes) -> SignedOffer:
    if type(offer_id) is HexBytes:
        offer_id = offer_id.to_0x_hex()
    elif type(offer_id) is bytes:
        offer_id = "0x" + offer_id.hex()
    response = requests.get(f"{ERC20_SERVICE_BASE_URL}/offers/{offer_id}")
    if response.status_code != 200:
        print(response.text)
    response.raise_for_status()
    offer_data = response.json()
    return _parse_offer_data(offer_data)


def get_offers(**filters) -> list[SignedOffer]:
    results = []
    more_pages = True
    page = 1
    while more_pages:
        filters["page"] = page
        query_params = "&".join(f"{k}={v}" for k, v in filters.items())
        response = requests.get(f"{ERC20_SERVICE_BASE_URL}/offers?{query_params}")
        if response.status_code != 200:
            print(response.text)
        response.raise_for_status()
        response_json = response.json()
        results.extend(response_json["offers"])
        more_pages = response_json.get("page") < response_json.get("total_pages")

    return [_parse_offer_data(offer_data) for offer_data in results]


def get_loan(loan_id: str | bytes | HexBytes) -> Loan:
    if type(loan_id) is HexBytes:
        loan_id = loan_id.to_0x_hex()
    elif type(loan_id) is bytes:
        loan_id = "0x" + loan_id.hex()
    response = requests.get(f"{ERC20_SERVICE_BASE_URL}/loans/{loan_id}")
    if response.status_code != 200:
        print(response.text)
    response.raise_for_status()

    loan_data = response.json()
    loan = _parse_loan_data(loan_data)

    loan_hash = compute_loan_hash(loan)
    print(f"loan_hash: {loan_hash.hex()}")

    return loan


def get_loans(**filters) -> list[Loan]:
    results = []
    more_pages = True
    page = 1
    while more_pages:
        filters["page"] = page
        query_params = "&".join(f"{k}={v}" for k, v in filters.items())
        response = requests.get(f"{ERC20_SERVICE_BASE_URL}/loans?{query_params}")
        if response.status_code != 200:
            print(response.text)
        response.raise_for_status()
        response_json = response.json()
        results.extend(response_json["loans"])
        more_pages = response_json.get("page") < response_json.get("total_pages")

    return [_parse_loan_data(loan_data) for loan_data in results]


def get_kyc(wallet: str, p2p_contract) -> SignedWalletValidation | None:
    response = requests.get(f"{ERC20_SERVICE_BASE_URL}/kyc/{wallet}")
    if response.status_code != 200:
        print(response.text)
    response.raise_for_status()
    validator = p2p_contract.kyc_validator_addr()
    kyc_data = response.json().get("validations").get(validator)
    if not kyc_data:
        return None
    wallet_validation = WalletValidation(kyc_data["validation"]["wallet"], int(kyc_data["validation"]["expiration_time"]))
    signature_data = kyc_data["signature"]
    signature = Signature(int(signature_data["v"]), signature_data["r"], signature_data["s"])
    return SignedWalletValidation(wallet_validation, signature) if kyc_data else None


def _create_offer_backend(signer: Account, **offer):
    filtered_offer = {k: v for k, v in offer.items() if k in Offer._fields}
    contract = ape.Contract(offer.get("p2p_contract"))
    filtered_offer["principal"] = int(filtered_offer["principal"])
    filtered_offer["apr"] = int(filtered_offer["apr"])
    filtered_offer["origination_fee_bps"] = int(filtered_offer.get("origination_fee_bps", 0))
    filtered_offer["tracing_id"] = bytes.fromhex(filtered_offer.get("tracing_id", ZERO_BYTES32.hex()))
    filtered_offer["expiration"] = int(filtered_offer.get("expiration", 0)) or FAR_AWAY_IN_THE_FUTURE
    filtered_offer["lender"] = filtered_offer.get("lender", signer.address)
    filtered_offer["payment_token"] = filtered_offer.get("payment_token", contract.payment_token())
    filtered_offer["collateral_token"] = filtered_offer.get("collateral_token", contract.collateral_token())
    filtered_offer["duration"] = int(filtered_offer.get("duration", 0))
    filtered_offer["available_liquidity"] = int(filtered_offer.get("available_liquidity", filtered_offer["principal"]))

    _offer = Offer(**filtered_offer)

    if _offer.tracing_id == ZERO_BYTES32:
        _offer = _offer._replace(tracing_id=random.randbytes(32))

    chain = offer.get("chain", CHAIN)
    verifying_contract = offer.get("p2p_contract")
    signed_offer = sign_offer(_offer, signer, verifying_contract)
    sig = signed_offer.signature

    payload = {
        "offer_display_type": offer.get("offer_display_type", "AUTOMATIC"),
        "principal": str(_offer.principal),
        "apr": _offer.apr,
        "payment_token": _offer.payment_token,
        "collateral_token": _offer.collateral_token,
        "duration": _offer.duration,
        "origination_fee_bps": _offer.origination_fee_bps,
        "min_collateral_amount": str(_offer.min_collateral_amount),
        "max_iltv": _offer.max_iltv,
        "available_liquidity": str(_offer.available_liquidity),
        "call_eligibility": _offer.call_eligibility,
        "call_window": _offer.call_window,
        "soft_liquidation_ltv": _offer.soft_liquidation_ltv,
        "oracle_addr": _offer.oracle_addr,
        "expiration": _offer.expiration,
        "lender": _offer.lender,
        "borrower": _offer.borrower,
        "tracing_id": _offer.tracing_id.hex(),
        "p2p_contract": offer.get("p2p_contract"),
        "signature": {"v": sig.v, "r": sig.r.hex(), "s": sig.s.hex()},
    }
    response = requests.post(f"{ERC20_SERVICE_BASE_URL}/offers?chain={chain}", json=payload)

    if response.status_code != 200:
        print(response.text)
    response.raise_for_status()

    return response.json()


def create_offer_backend(signer: Account, approve=True, **offer) -> SignedOffer:  # noqa: FBT002
    contract_key = offer.get("contract_key")
    p2p_contract = dm.context.contracts.get(f"p2p.{contract_key}").contract
    _offer = offer | {"p2p_contract": p2p_contract.address}
    print(f"Signing offer for {p2p_contract.address}")
    response_data = _create_offer_backend(signer, **_offer)
    offer = _parse_offer_data(response_data)
    if approve:
        payment_contract = ape.Contract(offer.offer.payment_token)
        allowance = payment_contract.allowance(signer.address, p2p_contract)
        if allowance < offer.offer.available_liquidity:
            print(f"Approving {offer.offer.available_liquidity} for {p2p_contract}")
            payment_contract.approve(p2p_contract, offer.offer.available_liquidity, sender=signer)
        balance = payment_contract.balanceOf(signer.address)
        if balance < offer.offer.available_liquidity:
            raise ValueError(f"Not enough balance {balance} to cover {offer.offer.available_liquidity}")
    return offer


def _parse_offer_data(offer_data) -> SignedOffer:
    offer = Offer(
        principal=int(offer_data["principal"]),
        apr=int(offer_data["apr"]),
        payment_token=offer_data["payment_token"],
        collateral_token=offer_data["collateral_token"],
        duration=int(offer_data["duration"]),
        origination_fee_bps=int(offer_data["origination_fee_bps"]),
        min_collateral_amount=int(offer_data["min_collateral_amount"]),
        max_iltv=int(offer_data["max_iltv"]),
        available_liquidity=int(offer_data["available_liquidity"]),
        call_eligibility=int(offer_data["call_eligibility"]),
        call_window=int(offer_data["call_window"]),
        soft_liquidation_ltv=int(offer_data["soft_liquidation_ltv"]),
        oracle_addr=offer_data["oracle_addr"],
        expiration=int(offer_data.get("expiration") or 0),
        lender=offer_data["lender"],
        borrower=offer_data["borrower"],
        tracing_id=HexBytes(offer_data["tracing_id"]),
    )
    signature_data = offer_data["signature"]
    signature = Signature(int(signature_data["v"]), signature_data["r"], signature_data["s"])
    return SignedOffer(offer, signature)


def _parse_loan_data(loan_data: dict) -> Loan:
    return Loan(
        id=HexBytes(loan_data["loan_id"]),
        offer_id=HexBytes(loan_data["offer_id"]),
        offer_tracing_id=HexBytes(loan_data["offer_tracing_id"]),
        initial_amount=int(loan_data["initial_amount"]),
        amount=int(loan_data["principal"]),
        apr=int(loan_data["apr"]),
        payment_token=loan_data["payment_token"],
        maturity=int(loan_data["maturity"]),
        start_time=int(loan_data["start_time"]),
        accrual_start_time=int(loan_data["accrual_start_time"]),
        borrower=loan_data["borrower"],
        lender=loan_data["lender"],
        collateral_token=loan_data["collateral_token"],
        collateral_amount=int(loan_data["collateral_amount"]),
        min_collateral_amount=int(loan_data["min_collateral_amount"]),
        origination_fee_amount=int(loan_data["origination_fee_amount"]),
        protocol_upfront_fee_amount=int(loan_data["protocol_upfront_fee_amount"]),
        protocol_settlement_fee=int(loan_data["protocol_settlement_fee"]),
        soft_liquidation_fee=int(loan_data["soft_liquidation_fee"]),
        call_eligibility=int(loan_data["call_eligibility"]),
        call_window=int(loan_data["call_window"]),
        soft_liquidation_ltv=int(loan_data["soft_liquidation_ltv"]),
        oracle_addr=loan_data["oracle_addr"],
        initial_ltv=int(loan_data["initial_ltv"]),
        call_time=int(loan_data.get("call_time") or 0),
    )


def from_hexstr_to_bytes(hex_str: str) -> bytes:
    hex_str = hex_str.removeprefix("0x")
    return bytes.fromhex(hex_str)


def from_hexstr_to_int(hex_str: str) -> bytes:
    hex_str = hex_str.removeprefix("0x")
    return int(hex_str, 16)


def create_loan(  # noqa: PLR0917
    signed_offer: SignedOffer,
    principal: int,
    collateral_amount: int,
    contract,
    kyc_borrower: SignedWalletValidation | None = None,
    kyc_lender: SignedWalletValidation | None = None,
    *,
    kyc_validator: Account = dm.owner,
    sender,
):
    offer = signed_offer.offer
    kyc_validator_contract = contract.kyc_validator_addr()
    if kyc_borrower is None:
        print("Signing KYC for borrower")
        kyc_borrower = sign_kyc(sender.address, kyc_validator, kyc_validator_contract)
    if kyc_lender is None:
        print("Signing KYC for lender")
        kyc_lender = sign_kyc(offer.lender, kyc_validator, kyc_validator_contract)

    _kyc_borrower = SignedWalletValidation(
        kyc_borrower.validation,
        Signature(
            kyc_borrower.signature.v,
            int(HexBytes(kyc_borrower.signature.r).to_0x_hex(), base=16),
            int(HexBytes(kyc_borrower.signature.s).to_0x_hex(), base=16),
        ),
    )
    _kyc_lender = SignedWalletValidation(
        kyc_lender.validation,
        Signature(
            kyc_lender.signature.v,
            int(HexBytes(kyc_lender.signature.r).to_0x_hex(), base=16),
            int(HexBytes(kyc_lender.signature.s).to_0x_hex(), base=16),
        ),
    )

    payment_contract = ape.Contract(offer.payment_token)
    collateral_contract = ape.Contract(offer.collateral_token)

    approval = principal - offer.origination_fee_bps * principal // BPS
    assert payment_contract.balanceOf(offer.lender) >= approval, f"Lender must have {approval}"
    assert payment_contract.allowance(offer.lender, contract.address) >= approval, f"Lender must approve {approval}"

    if collateral_contract.allowance(sender, contract.address) < collateral_amount:
        print(f"Approving {collateral_amount} for {collateral_contract.address}")
        collateral_contract.approve(contract.address, collateral_amount, sender=sender)

    print(f"{signed_offer=}")
    print(f"{_kyc_borrower=}")
    print(f"{_kyc_lender=}")
    return contract.create_loan(
        signed_offer,
        principal,
        collateral_amount,
        _kyc_borrower,
        _kyc_lender,
        sender=sender,
    )


def pay_loan(loan, contract, *, sender):
    loan_hash = compute_loan_hash(loan)
    print(f"loan_hash: {loan_hash.hex()}")

    loan_hash_in_contract = contract.loans(loan.id)
    print(f"loan_hash_in_contract: {loan_hash_in_contract.hex()}")

    payment_contract = ape.Contract(loan.payment_token)
    amount_to_approve = loan.amount + loan.get_interest(now() + 60)

    if payment_contract.allowance(sender, contract.address) < amount_to_approve:
        print(f"Approving {amount_to_approve} for {contract.address}")
        payment_contract.approve(contract.address, amount_to_approve, sender=sender)

    contract.settle_loan(loan, sender=sender)


def add_collateral(loan: Loan, contract, collateral_amount: int, sender):
    collateral_contract = ape.Contract(loan.collateral_token)

    if collateral_contract.allowance(loan.borrower, contract.address) < collateral_amount:
        print(f"Approving {collateral_amount} for {contract.address}")
        collateral_contract.approve(contract.address, collateral_amount, sender=sender)

    contract.add_collateral_to_loan(loan, collateral_amount, sender=sender)


def remove_collateral(loan: Loan, contract, collateral_amount: int, sender):
    contract.remove_collateral_from_loan(loan, collateral_amount, sender=sender)


def refinance(  # noqa: PLR0917
    loan: Loan,
    offer: SignedOffer,
    contract,
    principal: int,
    collateral_amount: int,
    kyc_lender: SignedWalletValidation | None,
    sender,
):
    if not collateral_amount:
        collateral_amount = max(loan.collateral_amount, offer.offer.min_collateral_amount)

    if kyc_lender is None:
        print("Signing KYC for borrower")
        kyc_lender = sign_kyc(offer.offer.lender, dm.owner, contract.kyc_validator_addr())

    _kyc_lender = SignedWalletValidation(
        kyc_lender.validation,
        Signature(
            kyc_lender.signature.v,
            HexBytes(kyc_lender.signature.r).to_0x_hex(),
            HexBytes(kyc_lender.signature.s).to_0x_hex(),
        ),
    )

    delta_borrower, _, delta_new_lender, _ = calc_deltas(loan, offer.offer, 0, contract, now() + 60)
    payment_contract = ape.Contract(offer.offer.payment_token)
    if delta_borrower < 0:
        approval = -delta_borrower
        if payment_contract.allowance(sender, contract.address) < approval:
            print(f"Approving {approval} for {contract.address}")
            payment_contract.approve(contract.address, approval, sender=sender)
    if delta_new_lender < 0:
        approval = -delta_new_lender
        assert payment_contract.balanceOf(offer.offer.lender) >= approval, f"New lender must have {approval}"
        assert payment_contract.allowance(offer.offer.lender, contract.address) >= approval, f"Lender must approve {approval}"

    return contract.replace_loan(loan, offer, principal, collateral_amount, _kyc_lender, sender=sender)


def calc_ltv(principal, collateral_amount, principal_token, collateral_token, oracle, *, oracle_reverse=False):
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    if oracle_reverse:
        rate, oracle_decimals = oracle_decimals, rate
    principal_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    return (
        principal * BPS * oracle_decimals * collateral_token_decimals // (collateral_amount * rate * principal_token_decimals)
    )


def calc_deltas(loan: Loan, offer: Offer, principal: int, contract, timestamp: int = 0) -> (int, int, int, int):
    if not timestamp:
        timestamp = now()
    interest = loan.amount * loan.apr * (timestamp - loan.accrual_start_time) // (365 * DAY * BPS)
    protocol_settlement_fee = interest * loan.protocol_settlement_fee // BPS
    outanding_debt = loan.amount + interest
    new_principal = outanding_debt if principal == 0 else principal
    origination_fee_amount = offer.origination_fee_bps * new_principal // BPS
    protocol_fee_amount = contract.protocol_upfront_fee() * new_principal // BPS

    delta_borrower = new_principal - outanding_debt - origination_fee_amount
    delta_lender = outanding_debt - protocol_settlement_fee
    delta_new_lender = origination_fee_amount - new_principal - protocol_fee_amount
    delta_protocol = protocol_settlement_fee + protocol_fee_amount

    return delta_borrower, delta_lender, delta_new_lender, delta_protocol


def contract_size(path):
    c = vyper.compile_code(Path(path).read_text(encoding="utf-8"))
    codesize = len(c["bytecode"]) // 2
    limit = 24 * 1024
    print(f"{path} size: {codesize} / {limit} bytes ({limit - codesize} left)")
    return codesize


def contract_sizes():
    for path in Path("contracts").rglob("*.vy"):
        contract_size(path)


def ape_init_extras():
    globals()["dm"] = dm
    globals()["owner"] = dm.owner
    for k, v in dm.context.contracts.items():
        globals()[k.replace(".", "_").replace("-", "_")] = v.contract
        print(k.replace(".", "_"), v.contract)
    for k, v in dm.context.config.items():
        globals()[k.replace(".", "_").replace("-", "_")] = v
