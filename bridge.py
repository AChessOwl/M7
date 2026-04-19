from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json


def connect_to(chain):
    if chain == 'source':  # Avalanche Fuji
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':  # BSC testnet
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
    else:
        return None

    w3 = Web3(Web3.HTTPProvider(api_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    with open(contract_info, 'r') as f:
        contracts = json.load(f)
    return contracts[chain]


def get_events_chunked(contract_event, from_block, to_block):
    """Avoid BSC RPC limit errors by querying small block ranges"""
    events = []
    step = 2  # small chunk size (important!)

    for start in range(from_block, to_block + 1, step):
        end = min(start + step - 1, to_block)
        try:
            chunk = contract_event.get_logs(from_block=start, to_block=end)
            events.extend(chunk)
        except Exception as e:
            print(f"Skipping blocks {start}-{end}: {e}")

    # Sort to preserve correct order
    events = sorted(events, key=lambda e: (e['blockNumber'], e['logIndex']))
    return events


def scan_blocks(chain, contract_info="contract_info.json"):

    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return

    source_info = get_contract_info('source', contract_info)
    dest_info = get_contract_info('destination', contract_info)

    warden_private_key = source_info['private_key']

    source_w3 = connect_to('source')
    dest_w3 = connect_to('destination')

    source_contract = source_w3.eth.contract(
        address=Web3.to_checksum_address(source_info['address']),
        abi=source_info['abi']
    )

    dest_contract = dest_w3.eth.contract(
        address=Web3.to_checksum_address(dest_info['address']),
        abi=dest_info['abi']
    )

    if chain == 'source':
        w3 = source_w3
        latest_block = w3.eth.block_number
        from_block = max(0, latest_block - 5)

        print(f"Scanning blocks {from_block}-{latest_block} on source")

        events = get_events_chunked(
            source_contract.events.Deposit,
            from_block,
            latest_block
        )

        for evt in events:
            token = evt['args']['token']
            recipient = evt['args']['recipient']
            amount = evt['args']['amount']

            print(f"  Deposit: token={token} recipient={recipient} amount={amount}")

            warden_account = dest_w3.eth.account.from_key(warden_private_key)
            nonce = dest_w3.eth.get_transaction_count(
                warden_account.address, 'pending'
            )

            tx = dest_contract.functions.wrap(
                token,
                recipient,
                amount
            ).build_transaction({
                'from': warden_account.address,
                'nonce': nonce,
                'gas': 300000,
                'gasPrice': dest_w3.eth.gas_price,
                'chainId': 97  # BSC testnet
            })

            signed_tx = dest_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = dest_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = dest_w3.eth.wait_for_transaction_receipt(tx_hash)

            print(f"  wrap() tx: {tx_hash.hex()} status: {receipt['status']}")

    else:
        w3 = dest_w3
        latest_block = w3.eth.block_number
        from_block = max(0, latest_block - 5)

        print(f"Scanning blocks {from_block}-{latest_block} on destination")

        events = get_events_chunked(
            dest_contract.events.Unwrap,
            from_block,
            latest_block
        )

        for evt in events:
            underlying_token = evt['args']['underlying_token']
            recipient = evt['args']['to']
            amount = evt['args']['amount']

            print(f"  Unwrap: token={underlying_token} recipient={recipient} amount={amount}")

            warden_account = source_w3.eth.account.from_key(warden_private_key)
            nonce = source_w3.eth.get_transaction_count(
                warden_account.address, 'pending'
            )

            tx = source_contract.functions.withdraw(
                underlying_token,
                recipient,
                amount
            ).build_transaction({
                'from': warden_account.address,
                'nonce': nonce,
                'gas': 300000,
                'gasPrice': source_w3.eth.gas_price,
                'chainId': 43113  # Avalanche Fuji
            })

            signed_tx = source_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash)

            print(f"  withdraw() tx: {tx_hash.hex()} status: {receipt['status']}")
