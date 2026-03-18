# Architectural Patterns

This document describes the architectural patterns and design conventions used throughout the codebase.

## 1. Delegatecall Facet Pattern

The protocol uses a diamond-like facet pattern where complex operations are delegated to separate contracts.

**Location**: `contracts/v1/P2PLendingVaultedErc20.vy:620-636` (liquidation), `contracts/v1/P2PLendingVaultedErc20.vy:958-979` (refinance)

**Pattern**:
```vyper
raw_call(
    liquidation_addr,
    abi_encode(
        loan,
        payment_token,
        # ... immutable context passed explicitly
        method_id=method_id("partially_liquidate_loan(...)")
    ),
    is_delegate_call=True
)
```

**Key aspects**:
- Facet contracts (`P2PLendingVaultedLiquidation`, `P2PLendingVaultedRefinance`) share storage with main contract
- Immutable values are passed explicitly since delegatecall doesn't preserve them
- Facets initialize the same base module to share struct definitions

## 2. Externalized State Pattern

Full loan/offer data is not stored on-chain. Only hashes are stored to reduce gas costs.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:233-239`

**Pattern**:
```vyper
# Storage only holds hash
loans: public(HashMap[bytes32, bytes32])

@view
@internal
def _is_loan_valid(loan: Loan) -> bool:
    return self.loans[loan.id] == self._loan_state_hash(loan)

@pure
@internal
def _loan_state_hash(loan: Loan) -> bytes32:
    return keccak256(abi_encode(loan))
```

**Usage**: Callers must pass full `Loan` struct; contract validates hash matches stored value.

## 3. Module Composition with initializes/exports

Vyper 0.4's module system is used for code reuse while maintaining storage layout consistency.

**Location**: `contracts/v1/P2PLendingVaultedErc20.vy:10-13`

**Pattern**:
```vyper
from contracts.v1 import P2PLendingVaultedBase as base

initializes: base
exports: base.__interface__
```

**Key aspects**:
- `initializes` ensures base module's storage is properly initialized
- `exports` exposes base module's public interface
- All contracts in the facet pattern must initialize the same base

## 4. CREATE2 Minimal Proxy Vaults

Vaulted and Securitize versions use CREATE2 for deterministic per-borrower vault addresses.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:400-407`

**Pattern**:
```vyper
@internal
def _create_vault_if_needed(wallet: address, vault_impl_addr: address, payment_token: address) -> vault.Vault:
    _vault: address = self._wallet_to_vault(wallet, vault_impl_addr)
    if not _vault.is_contract:
        _vault = create_minimal_proxy_to(vault_impl_addr, salt=convert(wallet, bytes32))
        extcall vault.Vault(_vault).initialise(wallet, payment_token)
    return vault.Vault(_vault)
```

**Address computation** (`contracts/v1/P2PLendingVaultedBase.vy:410-422`):
- Deterministic via `keccak256(0xff + deployer + salt + bytecode_hash)`
- Salt is the borrower's wallet address

## 5. EIP-712 Typed Data Signatures

Offers and KYC validations use EIP-712 for secure off-chain signing.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:160-168` (type definitions), `contracts/v1/P2PLendingVaultedBase.vy:243-273` (verification)

**Pattern**:
```vyper
DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
OFFER_TYPE_HASH: constant(bytes32) = keccak256(OFFER_TYPE_DEF)

@internal
def _is_offer_signed_by_lender(signed_offer: SignedOffer, offer_sig_domain_separator: bytes32) -> bool:
    message_hash: bytes32 = keccak256(
        concat(
            convert("\x19\x01", Bytes[2]),
            abi_encode(offer_sig_domain_separator, keccak256(abi_encode(OFFER_TYPE_HASH, signed_offer.offer)))
        )
    )
    signer: address = ecrecover(message_hash, ...)
    # Also supports EIP-1271 for contract wallets
```

## 6. Immutable Configuration Pattern

Protocol parameters that shouldn't change after deployment are immutable.

**Location**: `contracts/v1/P2PLendingVaultedErc20.vy:229-246`

**Immutables**:
- Token addresses (`payment_token`, `collateral_token`)
- Oracle config (`oracle_addr`, `oracle_reverse`)
- Fee limits (`max_protocol_upfront_fee`, `max_protocol_settlement_fee`)
- Facet addresses (`refinance_addr`, `liquidation_addr`)
- Vault implementation (`vault_impl_addr`)

**Mutables** (owner-controlled):
- Current fee rates
- Protocol wallet
- Authorized proxies

## 7. Two-Phase Ownership Transfer

Prevents accidental ownership loss through propose/claim pattern.

**Location**: `contracts/v1/P2PLendingVaultedErc20.vy:409-436`

**Pattern**:
```vyper
@external
def propose_owner(_address: address):
    assert msg.sender == base.owner
    base.proposed_owner = _address

@external
def claim_ownership():
    assert msg.sender == base.proposed_owner
    base.owner = msg.sender
    base.proposed_owner = empty(address)
```

## 8. Pending Transfers Fallback

Handles ERC20 tokens that may fail on transfer (e.g., USDT).

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:283-298`, `contracts/v1/P2PLendingVault.vy:103-129`

**Pattern**:
```vyper
@internal
def _send_funds(_to: address, _amount: uint256, payment_token: address):
    success, response = raw_call(
        payment_token,
        abi_encode(_to, _amount, method_id=method_id("transfer(address,uint256)")),
        max_outsize=32,
        revert_on_failure=False
    )
    if not success or not convert(response, bool):
        self.pending_transfers[_to] += _amount  # Can be claimed later
```

## 9. Authorized Proxy Pattern

Allows trusted contracts to act on behalf of users.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:321-322`

**Pattern**:
```vyper
@internal
def _check_user(user: address) -> bool:
    return msg.sender == user or (self.authorized_proxies[msg.sender] and user == tx.origin)
```

**Usage in loan creation** (`contracts/v1/P2PLendingVaultedErc20.vy:479`):
```vyper
borrower: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin
```

## 10. Test NamedTuple Mirroring

Tests use Python NamedTuples that mirror Vyper structs for type safety.

**Location**: `tests/p2p_erc20_vaulted/conftest_base.py:67-128`

**Pattern**:
```python
class Offer(NamedTuple):
    principal: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    # ... matches Vyper struct field order exactly

class Loan(NamedTuple):
    id: bytes = ZERO_BYTES32
    # ... all 26 fields matching Vyper struct

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600 * BPS)
```

## 11. LTV-Based Risk Management

Loan health is monitored via Loan-to-Value ratio using oracle prices.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:352-355`

**Pattern**:
```vyper
@view
@internal
def _compute_ltv(collateral_amount: uint256, amount: uint256, convertion_rate: UInt256Rational, ...) -> uint256:
    return amount * BPS * convertion_rate.denominator * collateral_token_decimals // (collateral_amount * convertion_rate.numerator * payment_token_decimals)
```

**Thresholds**:
- `initial_ltv`: Maximum LTV at loan creation
- `liquidation_ltv`: Threshold for partial liquidation trigger

## 12. Committed Liquidity Tracking

Prevents offer overuse by tracking committed principal per offer.

**Location**: `contracts/v1/P2PLendingVaultedBase.vy:197-209`

**Pattern**:
```vyper
commited_liquidity: public(HashMap[bytes32, uint256])  # key = hash(lender, tracing_id)

@internal
def _check_and_update_offer_state(offer: SignedOffer, amount: uint256):
    liquidity_key: bytes32 = self._commited_liquidity_key(offer.offer.lender, offer.offer.tracing_id)
    commited_liquidity: uint256 = self.commited_liquidity[liquidity_key]
    assert commited_liquidity + amount <= offer.offer.available_liquidity, "offer fully utilized"
    self.commited_liquidity[liquidity_key] = commited_liquidity + amount
```

## 13. Securitize Redemption Pattern

The Securitize version supports a collateral redemption workflow where DS Tokens are converted back to payment tokens.

**Location**: `contracts/v1/P2PLendingSecuritizeBase.vy:474-498`, `contracts/v1/P2PLendingSecuritizeErc20.vy:1141-1199`

**Pattern**:
```vyper
# Loan struct includes redemption fields
struct Loan:
    # ... other fields
    vault_id: uint256              # Each loan has its own vault
    redeem_start: uint256          # Timestamp when redemption started (0 = not redeemed)
    redeem_residual_collateral: uint256  # Collateral kept in vault after redemption

# Redemption result is signed by protocol owner
struct RedeemResult:
    vault: address
    collateral_redeemed: uint256
    payment_redeemed: uint256
    timestamp: uint256

@internal
def _is_loan_redeem_concluded(loan: Loan, _vault: vault.Vault, redeem_result: SignedRedeemResult) -> bool:
    if loan.redeem_start == 0:
        return False
    if redeem_result.result.timestamp < loan.redeem_start:
        return False
    self._validate_redeem_result_sig(redeem_result)  # Verify owner signature
    return True
```

**Key aspects**:
- Borrower initiates redemption via `redeem()`, sending collateral to `securitize_redemption_wallet`
- Settlement/liquidation wait for signed `RedeemResult` from protocol owner
- Mixed balances (payment token + remaining collateral) handled in vault

## 14. Multiple Vaults per Borrower (Securitize)

Unlike the standard vaulted version, Securitize creates a new vault for each loan.

**Location**: `contracts/v1/P2PLendingSecuritizeBase.vy:524-529`

**Pattern**:
```vyper
vault_count: public(HashMap[address, uint256])  # Tracks vault count per borrower

@internal
def _create_new_vault(wallet: address, vault_impl_addr: address, payment_token: address) -> vault.Vault:
    _vault: vault.Vault = self._create_vault_if_needed(wallet, vault_impl_addr, payment_token)
    self.vault_count[wallet] += 1  # Increment for next loan
    return _vault
```

**Address computation uses vault_id**:
```vyper
@view
@internal
def _wallet_to_vault(wallet: address, vault_id: uint256, vault_impl_addr: address) -> address:
    _salt: bytes32 = keccak256(concat(convert(wallet, bytes20), convert(vault_id, bytes32)))
    # CREATE2 address computation...
```

## 15. Maturity Extension Pattern (Securitize)

Securitize contracts support extending loan maturity without full refinancing.

**Location**: `contracts/v1/P2PLendingSecuritizeRefinance.vy:379-504`

**Pattern**:
```vyper
struct LoanExtensionOffer:
    loan_id: bytes32
    original_maturity: uint256
    new_maturity: uint256

# Borrower-initiated (requires lender's signed offer)
@external
def extend_loan(loan: Loan, offer: SignedLoanExtensionOffer, new_maturity: uint256, ...):
    assert base._is_extension_offer_signed_by_lender(offer, loan.lender, ...)
    assert new_maturity > loan.maturity
    # Only maturity changes, all other fields preserved

# Lender-initiated (no signature needed)
@external
def extend_loan_lender(loan: Loan, new_maturity: uint256):
    assert base._check_user(loan.lender)
    assert new_maturity > loan.maturity
    # Direct maturity update
```

## 16. SecuritizeSwap Integration

Vaults can purchase DS tokens from stablecoins via SecuritizeSwap.

**Location**: `contracts/v1/P2PLendingVaultSecuritize.vy:187-211`

**Pattern**:
```vyper
interface SecuritizeSwap:
    def calculateDsTokenAmount(_stableCoinAmount: uint256) -> DsTokenAmountResult: view
    def swap(_liquidityAmount: uint256, _minOutAmount: uint256): nonpayable

@external
def buy(payment_token: address, min_ds_token_amount: uint256, stable_coin_amount: uint256):
    assert self._check_user(self.owner)  # Only vault owner

    securitize_swap_contract: address = staticcall SecuritizeDSToken(self.token).getDSService(1<<14)
    ds_token_amount: DsTokenAmountResult = staticcall SecuritizeSwap(securitize_swap_contract).calculateDsTokenAmount(stable_coin_amount)

    extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount)
    extcall IERC20(payment_token).approve(securitize_swap_contract, stable_coin_amount)
    extcall SecuritizeSwap(securitize_swap_contract).swap(stable_coin_amount, min_ds_token_amount)

    # Purchased tokens go to pending_transfers for owner to claim
    self.pending_transfers[self.owner] += ds_token_amount.ds_token_amount
```
