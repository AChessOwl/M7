from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware #Necessary for POA chains
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc" #AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/" #BSC testnet

    if chain in ['source','destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r')  as f:
            contracts = json.load(f)
    except Exception as e:
        print( f"Failed to read contract info\nPlease contact your instructor\n{e}" )
        return 0
    return contracts[chain]



def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """

    # This is different from Bridge IV where chain was "avax" or "bsc"
    if chain not in ['source','destination']:
        print( f"Invalid chain: {chain}" )
        return 0
    
    warden_private_key = "0x0f0fc26a06b87c3b2eb6b9fc5c804eaab57fa68a6efa8f3b0e03da73238a5937"

    source_info = get_contract_info('source', contract_info)
    dest_info = get_contract_info('destination', contract_info)

    source_w3 = connect_to('source')
    dest_w3 = connect_to('destination')

    source_contract = source_w3.eth.contract(
        address=source_info['address'],
        abi=source_info['abi']
    )
    dest_contract = dest_w3.eth.contract(
        address=dest_info['address'],
        abi=dest_info['abi']
    )

    if chain == 'source':
        w3 = source_w3
        contract = source_contract
        event_name = 'Deposit'
    else:
        w3 = dest_w3
        contract = dest_contract
        event_name = 'Unwrap'

    latest_block = w3.eth.block_number
    from_block = latest_block - 5 if latest_block >= 5 else 0

    if chain == 'source':
        events = contract.events.Deposit.get_logs(from_block=from_block, to_block=latest_block)
        for evt in events:
            token = evt['args']['token']
            recipient = evt['args']['recipient']
            amount = evt['args']['amount']

            warden_account = dest_w3.eth.account.from_key(warden_private_key)
            nonce = dest_w3.eth.get_transaction_count(warden_account.address)
            tx = dest_contract.functions.wrap(token, recipient, amount).build_transaction({
                'from': warden_account.address,
                'nonce': nonce,
                'gas': 300000,
                'gasPrice': dest_w3.eth.gas_price,
            })
            signed_tx = dest_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = dest_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = dest_w3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"wrap() called on destination, tx hash: {tx_hash.hex()}, status: {receipt['status']}")

    else:
        events = contract.events.Unwrap.get_logs(from_block=from_block, to_block=latest_block)
        for evt in events:
            underlying_token = evt['args']['underlying_token']
            recipient = evt['args']['to']
            amount = evt['args']['amount']

            warden_account = source_w3.eth.account.from_key(warden_private_key)
            nonce = source_w3.eth.get_transaction_count(warden_account.address)
            tx = source_contract.functions.withdraw(underlying_token, recipient, amount).build_transaction({
                'from': warden_account.address,
                'nonce': nonce,
                'gas': 300000,
                'gasPrice': source_w3.eth.gas_price,
            })
            signed_tx = source_w3.eth.account.sign_transaction(tx, warden_private_key)
            tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"withdraw() called on source, tx hash: {tx_hash.hex()}, status: {receipt['status']}")