import json
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


def connect_to(chain):
    if chain == 'source':
        urls = [
            "https://api.avax-test.network/ext/bc/C/rpc",
        ]
    elif chain == 'destination':
        urls = [
            "https://data-seed-prebsc-1-s1.binance.org:8545/",
            "https://data-seed-prebsc-2-s1.binance.org:8545/",
            "https://data-seed-prebsc-1-s2.binance.org:8545/",
            "https://data-seed-prebsc-2-s2.binance.org:8545/",
            "https://data-seed-prebsc-1-s3.binance.org:8545/",
            "https://data-seed-prebsc-2-s3.binance.org:8545/",
        ]
    else:
        raise ValueError(f"Unknown chain: {chain}")

    for url in urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.is_connected():
                return w3
        except Exception:
            continue

    raise ConnectionError(f"Could not connect to any RPC for {chain}")


def get_contract_info(chain, contract_info_path="contract_info.json"):
    try:
        with open(contract_info_path, "r") as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract info: {e}")
        return None
    return contracts[chain]


def scan_blocks(chain, contract_info="contract_info.json"):
    if chain not in ('source', 'destination'):
        print(f"Invalid chain: {chain}")
        return

    warden_private_key = "0x0f0fc26a06b87c3b2eb6b9fc5c804eaab57fa68a6efa8f3b0e03da73238a5937"

    source_info = get_contract_info('source', contract_info)
    dest_info   = get_contract_info('destination', contract_info)
    if not source_info or not dest_info:
        return

    source_w3 = connect_to('source')
    dest_w3   = connect_to('destination')

    source_contract = source_w3.eth.contract(address=source_info['address'], abi=source_info['abi'])
    dest_contract   = dest_w3.eth.contract(address=dest_info['address'],     abi=dest_info['abi'])

    w3       = source_w3 if chain == 'source' else dest_w3
    contract = source_contract if chain == 'source' else dest_contract

    latest_block = w3.eth.block_number
    from_block   = max(0, latest_block - 5)
    print(f"Scanning blocks {from_block}-{latest_block} on {chain}")

    if chain == 'source':
        events = contract.events.Deposit.get_logs(from_block=from_block, to_block=latest_block)
        for evt in events:
            token     = evt['args']['token']
            recipient = evt['args']['recipient']
            amount    = evt['args']['amount']
            print(f"  Deposit: token={token} recipient={recipient} amount={amount}")

            warden  = dest_w3.eth.account.from_key(warden_private_key)
            nonce   = dest_w3.eth.get_transaction_count(warden.address, 'pending')
            tx      = dest_contract.functions.wrap(token, recipient, amount).build_transaction({
                'from': warden.address, 'nonce': nonce, 'gas': 300_000, 'gasPrice': dest_w3.eth.gas_price,
            })
            signed  = dest_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = dest_w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = dest_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            print(f"  wrap() called on destination, tx hash: {tx_hash.hex()}, status: {receipt['status']}")

    else:
        events = contract.events.Unwrap.get_logs(from_block=from_block, to_block=latest_block)
        for evt in events:
            underlying_token = evt['args']['underlying_token']
            recipient        = evt['args']['to']
            amount           = evt['args']['amount']
            print(f"  Unwrap: underlying={underlying_token} recipient={recipient} amount={amount}")

            warden  = source_w3.eth.account.from_key(warden_private_key)
            nonce   = source_w3.eth.get_transaction_count(warden.address, 'pending')
            tx      = source_contract.functions.withdraw(underlying_token, recipient, amount).build_transaction({
                'from': warden.address, 'nonce': nonce, 'gas': 300_000, 'gasPrice': source_w3.eth.gas_price,
            })
            signed  = source_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = source_w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            print(f"  withdraw() called on source, tx hash: {tx_hash.hex()}, status: {receipt['status']}")


if __name__ == "__main__":
    scan_blocks('source')
    scan_blocks('destination')
