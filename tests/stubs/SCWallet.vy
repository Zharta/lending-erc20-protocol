# @version 0.4.3

from ethereum.ercs import IERC165
from ethereum.ercs import IERC721
from ethereum.ercs import IERC20


interface EIP1271Signer:
    def is_valid_signature(hash: bytes32, signature: Bytes[65]) -> bytes4: view

implements: EIP1271Signer

# Structs

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

MALLEABILITY_THRESHOLD: constant(uint256) = 57896044618658097711785492504343953926418782139537452191302581570759080747168
EIP1271_MAGIC_VALUE: constant(bytes4) = 0x1626ba7e


owner: address

@deploy
def __init__(_owner: address):
    self.owner = _owner

@external
def approve_erc20(
    erc20: address,
    spender: address,
    amount: uint256
):
    assert msg.sender == self.owner, "only owner can approve"
    extcall IERC20(erc20).approve(spender, amount)

@external
def transfer_erc20(
    erc20: address,
    to: address,
    amount: uint256
):
    assert msg.sender == self.owner, "only owner can transfer"
    extcall IERC20(erc20).transfer(to, amount)


@external
@view
def is_valid_signature(hash: bytes32, signature: Bytes[65]) -> bytes4:
    r: uint256 = convert(slice(signature, 0, 32), uint256)
    s: uint256 = convert(slice(signature, 32, 32), uint256)
    v: uint8 = convert(slice(signature, 64, 1), uint8)

    assert s <= MALLEABILITY_THRESHOLD, "invalid signature"

    signer: address = ecrecover(hash, v, r, s)

    return EIP1271_MAGIC_VALUE if signer == self.owner else 0x00000000
