from typing import TypeVar

import pandas as pd

from ..treasury import (
    ERC20,
    Balances,
    Prices,
    TotalBalance,
    Treasury,
    make_balances_from_treasury_and_prices,
    make_prices_from_tokens,
    make_total_balance_from_balances,
    make_treasury_from_address,
    update_treasury_assets_from_whitelist,
    update_treasury_assets_risk_contributions,
)
from .helpers import make_zeroes

Balanceish = TypeVar("Balanceish", float, pd.Series)


def _resize_balances(
    balanceish_dict: dict[str, Balanceish],
    spread_percentage: int,
) -> dict[str, Balanceish]:
    downsizing_factor = (100 - spread_percentage) / 100.0

    return {k: b * downsizing_factor for k, b in balanceish_dict.items()}


def update_balances_with_spread(
    balances: Balances,
    spread_token_symbol: str,
    spread_percentage: int,
    start: str,
    end: str,
) -> Balances:
    def get_default_balance(histbal: pd.DataFrame) -> float:
        try:
            return histbal.loc[start]
        except KeyError:
            return 0

    initial_total_balance = sum(map(get_default_balance, balances.balances.values()))
    resized_balances_dict = _resize_balances(balances.balances, spread_percentage)
    zeroes_series = make_zeroes(start, end)
    spread_additional_token_balance = zeroes_series + (
        initial_total_balance * spread_percentage / 100.0
    )
    spread_additional_token_balance.name = (
        f"{spread_token_symbol} spread backtest balance"
    )
    if spread_token_symbol in resized_balances_dict:
        spread_additional_token_balance = spread_additional_token_balance.add(
            resized_balances_dict[spread_token_symbol], fill_value=0
        )
    resized_balances_dict[spread_token_symbol] = spread_additional_token_balance
    return Balances(balances=resized_balances_dict)


def update_treasury_assets_with_spread_balances(
    treasury: Treasury,
    balances: Balances,
    end: str,
    spread_token_name: str,
    spread_token_symbol: str,
    spread_token_address: str,
) -> Treasury:
    for asset in treasury.assets:
        asset.balance = balances.balances[asset.token_symbol].loc[end]
    try:
        treasury.get_asset(spread_token_symbol)
    except StopIteration:
        treasury.assets.append(
            ERC20(
                token_name=spread_token_name,
                token_symbol=spread_token_symbol,
                token_address=spread_token_address,
                balance=balances.balances[spread_token_symbol].loc[end],
            )
        )
    return treasury


async def build_spread_treasury_with_assets(
    treasury_address: str,
    chain_id: int,
    start: str,
    end: str,
    spread_token_name: str,
    spread_token_symbol: str,
    spread_token_address: str,
    spread_percentage: int,
) -> tuple[Treasury, Prices, Balances, TotalBalance]:
    treasury = await make_treasury_from_address(treasury_address, chain_id)

    token_symbols_and_addresses: set[tuple[str, str]] = {
        (asset.token_symbol, asset.token_address) for asset in treasury.assets
    }
    tokens_sa_with_spread_token = token_symbols_and_addresses | {
        (spread_token_symbol, spread_token_address)
    }

    prices = await make_prices_from_tokens(tokens_sa_with_spread_token)

    balances = await make_balances_from_treasury_and_prices(
        treasury.address, token_symbols_and_addresses, prices
    )

    treasury = update_treasury_assets_from_whitelist(
        treasury,
        prices.get_existing_token_symbols() | balances.get_existing_token_symbols(),
    )

    balances = update_balances_with_spread(
        balances,
        spread_token_symbol,
        spread_percentage,
        start,
        end,
    )
    treasury = update_treasury_assets_with_spread_balances(
        treasury,
        balances,
        end,
        spread_token_name,
        spread_token_symbol,
        spread_token_address,
    )

    total_balance = make_total_balance_from_balances(balances)

    treasury = update_treasury_assets_risk_contributions(
        treasury,
        prices,
        start,
        end,
    )

    return (
        treasury,
        prices,
        balances,
        total_balance,
    )
