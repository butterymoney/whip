# pylint: disable=duplicate-code
import json
from os import getenv
from typing import Any, Dict, List, Optional

import dateutil
from celery.utils.log import get_logger
from httpx import AsyncClient, HTTPStatusError, Timeout
from pytz import UTC

from ... import db
from ..types import ERC20, HistoricalPrice, Quote, Treasury

CACHE_HASH = "covalent_treasury"
CACHE_KEY_TEMPLATE = "{address}_{chain_id}_{date}"


async def _get_treasury_portfolio(
    treasury_address: str, chain_id: Optional[int] = 1
) -> Dict[str, Any]:
    cache_date = dateutil.utils.today(UTC).strftime("%Y-%m-%d")
    cache_key = CACHE_KEY_TEMPLATE.format(
        address=treasury_address, chain_id=chain_id, date=cache_date
    )
    if db.hexists(CACHE_HASH, cache_key):
        return json.loads(db.hget(CACHE_HASH, cache_key))

    timeout = Timeout(10.0, read=20.0, connect=25.0)
    async with AsyncClient(timeout=timeout) as client:
        url = (
            f"https://api.covalenthq.com/v1/{chain_id}/address/{treasury_address}/"
            + f"portfolio_v2/?&key=ckey_{getenv('COVALENT_KEY')}"
        )
        resp = await client.get(url)
        data = resp.json()["data"]

    db.hset(CACHE_HASH, cache_key, json.dumps(data))

    return data


async def get_treasury_portfolio(
    treasury_address: str, chain_id: Optional[int] = 1
) -> Optional[dict[str, Any]]:
    try:
        return await _get_treasury_portfolio(treasury_address, chain_id)
    except (
        HTTPStatusError,
        json.decoder.JSONDecodeError,
        KeyError,
    ) as error:
        logger = get_logger(__name__)
        if error.__class__ in [HTTPStatusError]:
            logger.error(
                "unable to receive a Covalent `portfolio_v2` API response",
                exc_info=error,
            )
            return {}
        logger.error(
            "error processing Covalent `portfolio_v2` API response", exc_info=error
        )
        return {}


async def get_treasury(portfolio: Dict[str, Any], whitelist: list[str]) -> Treasury:

    windows: List[HistoricalPrice] = []
    for item in portfolio["items"]:
        windows.append(
            HistoricalPrice(
                item["contract_address"],
                item["contract_name"],
                item["contract_ticker_symbol"],
                [
                    Quote(
                        dateutil.parser.parse(holding["timestamp"]),
                        holding["quote_rate"],
                    )
                    for holding in item["holdings"]
                ],
            )
        )

    # Certain tokens a treasury may hold are noted as spam.
    # To prevent these tokens from corrupting the data,
    # we filter them out via a whitelist provided by tokenlists.org
    assets = [
        ERC20(
            item["contract_name"],
            item["contract_ticker_symbol"],
            item["contract_address"],
            item["holdings"][0]["close"]["quote"],
        )
        for item in portfolio["items"]
        if item["holdings"][0]["close"]["quote"]
        and item["contract_address"] in whitelist
        and item["holdings"]
    ]

    return Treasury(portfolio["address"], assets, windows)
