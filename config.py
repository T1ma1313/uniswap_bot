from web3 import Web3


def _as_set(*addresses: str) -> set[str]:
    return {Web3.to_checksum_address(addr) for addr in addresses}


NETWORKS = {
    "base": {
        "factory": Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD"),
        "nfpm": Web3.to_checksum_address("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1"),
    },
    "eth": {
        "factory": Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        "nfpm": Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88"),
    },
    "arbitrum": {
        "factory": Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        "nfpm": Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88"),
    }
}

WRAPPED_NATIVE = {
    "eth": Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "base": Web3.to_checksum_address("0x4200000000000000000000000000000000000006"),
    "arbitrum": Web3.to_checksum_address("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"),
}

USDC_BY_NETWORK = {
    "eth": Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "base": Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
    "arbitrum": Web3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831"),
}

STABLES_BY_NETWORK = {
    "eth": _as_set(
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
    ),
    "base": _as_set(
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
    ),
    "arbitrum": _as_set(
        "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
        "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9",  # USDT
        "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",  # DAI
    ),
}
