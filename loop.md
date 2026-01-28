
# Offer creation

    initial_borrower_collateral = 94000000
    ltv = 6800

```python
    lender = me
    borrower = fe

    initial_borrower_collateral = 5 * int(1e6)
    ltv = 7000
    collateral_to_buy = max_collateral_to_buy(initial_borrower_collateral, ltv)
    collateral_amount = initial_borrower_collateral + collateral_to_buy
    oracle_price_num = common_oracle_acred_usd.latestRoundData()[1]
    oracle_price_den = 10 ** common_oracle_acred_usd.decimals()
    collateral_to_buy_value = collateral_to_buy * oracle_price_num // oracle_price_den
    principal = collateral_amount * oracle_price_num * ltv // (oracle_price_den * BPS)
    collateral_amount_value = collateral_amount * oracle_price_num // oracle_price_den
    vault = p2p_usdc_acred_securitize.wallet_to_vault(borrower)

    offer = Offer(
        apr=0,
        payment_token=common_usdc.address,
        collateral_token=common_acred.address,
        duration=86400*1,
        origination_fee_bps=0,
        min_collateral_amount=collateral_amount,
        max_iltv=ltv,
        available_liquidity=principal,
        call_eligibility=0 * 86400,
        call_window=0 * 86400,
        liquidation_ltv=5000,
        expiration=1 * 86400,
        lender=lender.address,
        borrower=ZERO_ADDRESS,
    )
    signed_offer = sign_offer(offer, lender, p2p_usdc_acred_securitize.address)
    kyc_borrower = sign_kyc(borrower.address, dm.owner, p2p_usdc_acred_securitize.address, expiration=now() + 86400)
    kyc_lender = sign_kyc(lender.address, dm.owner, p2p_usdc_acred_securitize.address, expiration=now() + 86400)
```


# Lender approvals

```python

    common_usdc.approve(p2p_usdc_acred_securitize.address, principal, sender=lender)

```


# Borrower approvals

Approve USDC [approve (0x095ea7b3)](https://etherscan.io/address/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48#writeProxyContract)

```python

    # common_usdc.approve(p2p_securitize_loop.address, collateral_to_buy_value, sender=borrower)
    print("spender=", dump_address(p2p_securitize_loop.address))
    print("value=", collateral_to_buy_value)

```

Approve ACRED [approve (0x095ea7b3)](https://etherscan.io/address/0x17418038ecF73BA4026c4f428547BF099706F27B#writeProxyContract)

```python

    # common_acred.approve(vault, collateral_amount - collateral_to_buy, sender=borrower)
    print("spender=", dump_address(vault))
    print("value=", collateral_amount - collateral_to_buy)

```


# Loan creation

Function [create_loan (0xf8564beb)](https://etherscan.io/address/0xee6749205063ab603e695a5ec96d8bea6e794fbf#writeContract)

```python

    dump_create_loan_proxy(
        signed_offer,
        principal,
        collateral_amount,
        kyc_borrower,
        kyc_lender,
        collateral_to_buy,
        collateral_to_buy_value,
        common_oracle_acred_usd.address
    )

```
