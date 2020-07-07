from functools import reduce
import json
import pickle
import requests

from utility.hash_util import hash_block
from utility.verification import Verification
from block import Block
from transaction import Transaction
from wallet import Wallet

MINING_REWARD = 10


class Blockchain:
    """The Blockchain class manages the chain of blocks as well as 
    open transactions and the node on which it's running.

    Attributes:
        :chain: The list of blocks
        :open_transactions (private): The list of open transactions
        :hosting_node: The connected node (which runs the blockchain).
    """

    def __init__(self, public_key, node_id):
        genesis_block = Block(0, '', [], 100, 0)
        self.__chain = [genesis_block]
        self.__open_transactions = []
        self.public_key = public_key
        self.__peer_nodes = set()
        self.node_id = node_id
        self.resolve_conflicts = False
        self.load_data()

    @property
    def chain(self):
        return self.__chain[:]

    @chain.setter
    def chain(self, value):
        self.__chain = value

    @property
    def open_transactions(self):
        return self.__open_transactions[:]

    @open_transactions.setter
    def open_transactions(self, value):
        self.__open_transactions = value

    @property
    def peer_nodes(self):
        return list(self.__peer_nodes)

    @peer_nodes.setter
    def peer_nodes(self, value):
        self.__peer_nodes = value

    def load_data(self):
        """Initialize blockchain + open transactions data from a file."""
        try:
            with open(f'blockchain-{self.node_id}.p', mode='rb') as file:
                file_content = pickle.loads(file.read())
                self.chain = file_content['chain']
                self.__open_transactions = file_content['ot']
                self.__peer_nodes = set(file_content['pn'])
        except (IOError, IndexError):
            print('Load data: No file provided')

    def save_data(self):
        """Save blockchain, open transactions and peer_nodes snapshot to a file."""
        try:
            with open(f'blockchain-{self.node_id}.p', mode='wb') as file:
                save_data = {
                    'chain': self.__chain,
                    'ot': self.__open_transactions,
                    'pn': self.__peer_nodes
                }
                file.write(pickle.dumps(save_data))
            print(f'Saved to blockchain-{self.node_id}.p')
        except IOError:
            print("saving failed!")

    def proof_of_work(self):
        """Generate a proof of work for the open transactions,
        the hash of the previous block and a random number 
        (which is guessed until it fits)."""
        last_block = self.__chain[-1]
        last_hash = hash_block(last_block)
        proof = 0

        while not Verification.valid_proof(self.__open_transactions, last_hash, proof):
            proof += 1
        return proof

    def get_balance(self, sender=None):
        """ Calculate and return the balance for a participant. """
        if sender is None:
            if self.public_key == None:
                return None
            participant = self.public_key
        else:
            participant = sender
        tx_sender = [[tx.amount for tx in block.transactions
                      if tx.sender == participant] for block in self.__chain]
        open_tx_sender = [
            tx.amount for tx in self.__open_transactions if tx.sender == participant
        ]
        tx_sender.append(open_tx_sender)
        amount_sent = reduce(lambda tx_sum, amount: tx_sum + sum(amount)
                             if len(amount) else tx_sum + 0, tx_sender, 0)
        tx_recipient = [[tx.amount for tx in block.transactions
                         if tx.recipient == participant] for block in self.__chain]
        amount_received = reduce(lambda tx_sum, amount: tx_sum +
                                 sum(amount) if len(amount)
                                 else tx_sum + 0, tx_recipient, 0)
        return amount_received - amount_sent

    def get_last_blockchain_value(self):
        """ Returns the last value of the
        current blockchain or None if empty. """
        if not len(self.__chain):
            return None
        return self.__chain[-1]

    def add_transaction(
            self,
            recipient,
            sender,
            signature,
            amount=1.0,
            is_receiving=False):
        """ Append a new value as well as the last
        blockchain value to the blockchain.

        Arguments:
            :param sender: The sender of the coins.
            :param recipient: The recipient of the coins.
            :param signature: The transaction signature.
            :param amount: The amount of coins sent
            with the transaction(default=1.0).
        """
        transaction = Transaction(sender, recipient, signature, amount)
        if Verification.verify_transaction(transaction, self.get_balance):
            self.__open_transactions.append(transaction)
            self.save_data()
            if not is_receiving:
                for node in self.__peer_nodes:
                    url = f'http://{node}/broadcast-transaction'
                    try:
                        response = requests.post(url, json={
                            'sender': sender, 'recipient': recipient, 'amount': amount, 'signature': signature})
                        if response.status_code == 400 or response.status_code == 500:
                            print('Transaction declined, needs resolving')
                            return False
                    except requests.exceptions.ConnectionError:
                        continue
            return True
        return False

    def mine_block(self):
        """Create a new block and add open transactions to it."""
        if self.public_key == None:
            return None
        last_block = self.__chain[-1]
        hashed_block = hash_block(last_block)
        proof = self.proof_of_work()
        reward_transaction = Transaction(
            'MINING', self.public_key, '', MINING_REWARD)
        copied_transactions = self.__open_transactions[:]
        for tx in copied_transactions:
            if not Wallet.verify_transaction(tx):
                return None
        copied_transactions.append(reward_transaction)
        block = Block(len(self.__chain), hashed_block,
                      copied_transactions, proof)
        self.__chain.append(block)
        self.__open_transactions = []
        self.save_data()
        for node in self.__peer_nodes:
            url = f'http://{node}/broadcast-block'
            converted_block = block.__dict__.copy()
            converted_block['transactions'] = [
                tx.__dict__ for tx in converted_block['transactions']]
            try:
                response = requests.post(url, json={'block': converted_block})
                if response.status_code == 400 or response.status_code == 500:
                    print('Block declined, needs resolving')
                    return None
                if response.status_code == 409:
                    self.resolve_conflicts = True
            except requests.exceptions.ConnectionError:
                continue
        return block

    def add_block(self, block):
        transactions = [Transaction(
            tx['sender'], tx['recipient'], tx['signature'], tx['amount']) for tx in block['transactions']]
        proof_is_valid = Verification.valid_proof(
            transactions[:-1], block['previous_hash'], block['proof'])
        hashes_match = hash_block(self.chain[-1]) == block['previous_hash']
        if not proof_is_valid or not hashes_match:
            return False
        converted_block = Block(
            block['index'], block['previous_hash'], transactions, block['proof'], block['timestamp'])
        self.__chain.append(converted_block)
        stored_transactions = self.__open_transactions[:]
        for incoming_tx in block['transactions']:
            for open_tx in stored_transactions:
                if open_tx.sender == incoming_tx['sender'] and open_tx.recipient == incoming_tx['recipient'] and open_tx.amount == incoming_tx['amount'] and open_tx.signature == incoming_tx['signature']:
                    try:
                        self.__open_transactions.remove(open_tx)
                    except ValueError:
                        print('Item was already removed')
        self.save_data()
        return True

    def resolve(self):
        """"""
        winner_chain = self.chain
        replace = False
        for node in self.__peer_nodes:
            url = f'http://{node}/chain'
            try:
                response = requests.get(url)
                node_chain = response.json()
                node_chain = [Block(
                    block['index'],
                    block['previous_hash'],
                    [Transaction(
                        tx['sender'],
                        tx['recipient'],
                        tx['signature'],
                        tx['amount'])
                        for tx in block['transactions']],
                    block['proof'],
                    block['timestamp'])
                    for block in node_chain]
                if len(node_chain) > len(winner_chain) and Verification.verify_chain(node_chain):
                    winner_chain = node_chain
                    replace = True
            except requests.exceptions.ConnectionError:
                continue
        self.resolve_conflicts = False
        self.chain = winner_chain
        if replace:
            self.__open_transactions = []
        self.save_data()
        return replace

    def add_peer_node(self, node):
        """Adds a new node to the peer node set

        Arguments:
            :param node: The node URL which should be added.
        """
        self.__peer_nodes.add(node)
        self.save_data()

    def remove_peer_node(self, node):
        """Removes a new node from the peer node set

        Arguments:
            :param node: The node URL which should be deleted.
        """
        self.__peer_nodes.discard(node)
        self.save_data()
