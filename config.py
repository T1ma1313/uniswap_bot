from web3 import Web3

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

STABLES = ["USDC", "USDT", "DAI"]

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