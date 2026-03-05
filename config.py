import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

NETWORKS = {
    "base": {
        "rpc": f"https://base-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_API_KEY')}",
        "factory": Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD"),
        "nfpm": Web3.to_checksum_address("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1"),
    },
    "eth": {
        "rpc": f"https://eth-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_API_KEY')}",
        "factory": Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        "nfpm": Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88"),
    },
    "arbitrum": {
        "rpc": f"https://arb-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_API_KEY')}",
        "factory": Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        "nfpm": Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88"),
    }
}

STABLES = ["USDC", "USDT", "DAI"]