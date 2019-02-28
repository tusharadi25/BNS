import hashlib
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4
import ipfsapi
from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)

from _thread import start_new_thread


def h(block):
    block_string = json.dumps(block, sort_keys=True).encode()
    return hashlib.sha256(block_string).hexdigest()


class Blockchain:
    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.nodes = set()
        self.genesis = self.new_block(prev_hash='0', proof=100)

    def register_node(self, address):
        parsed_url = urlparse(address)
        if parsed_url.netloc:
            self.nodes.add(parsed_url.netloc)
        elif parsed_url.path:
            # Accepts an URL without scheme like '192.168.0.5:5000'.
            self.nodes.add(parsed_url.path)
        else:
            raise ValueError('Invalid URL')

    def valid_chain(self, chain):
        last_block = chain[0]
        current_index = 1

        while current_index < len(chain):
            block = chain[current_index]
            last_block_hash = h(last_block)
            if block['previous_hash'] != last_block_hash:
                return False
            if not self.valid_proof(last_block['proof'], block['proof'], last_block_hash):
                return False
            last_block = block
            current_index += 1
        return True

    def resolve_conflicts(self):

        neighbours = self.nodes
        new_chain = None

        # We're only looking for chains longer than ours
        max_length = len(self.chain)
        print(neighbours)
        # Grab and verify the chains from all the nodes in our network
        for node in neighbours:
            response = requests.get(f'http://{node}:5000/chain')
            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                # Check if the length is longer and the chain is valid
                if length > max_length and self.valid_chain(chain):
                    max_length = length
                    new_chain = chain

        # Replace our chain if we discovered a new, valid chain longer than ours
        if new_chain:
            self.chain = new_chain
            return True

        return False

    def new_block(self, proof, prev_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time.time(),
            'transactions': self.current_transactions,
            'proof': proof,
            'previous_hash': prev_hash or h(self.chain[-1]),
        }
        self.current_transactions = []
        self.chain.append(block)
        return block

    def new_transaction(self, sender, recipient, domain, zoneHash):

        self.current_transactions.append({
            'senderID': sender,
            'buyerID': recipient,
            'domain': domain,
            'zoneHash': zoneHash,
        })
        return self.last_block['index'] + 1

    @property
    def last_block(self):
        return self.chain[-1]

    def proof_of_work(self, last_block):
        last_proof = last_block['proof']
        last_hash = h(last_block)
        proof = 0
        while self.valid_proof(last_proof, proof, last_hash) is False:
            proof += 1

        return proof

    @staticmethod
    def valid_proof(last_proof, proof, last_hash):
        guess = f'{last_proof}{proof}{last_hash}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"


app = Flask(__name__, static_folder=os.getcwd())
p = os.getcwd()
blockchain = Blockchain()
api = ipfsapi.connect('127.0.0.1', 5001)
print(api)


@app.route('/mine', methods=['GET'])
def mine():
    # We run the proof of work algorithm to get the next proof...
    last_block = blockchain.last_block
    proof = blockchain.proof_of_work(last_block)
    ipfsid = api.id()['ID']
    blockchain.new_transaction(
        sender="0",
        recipient=ipfsid,
        domain='www.bns.com',
        zoneHash='0000'
    )

    # Forge the new Block by adding it to the chain
    previous_hash = h(last_block)
    block = blockchain.new_block(proof, previous_hash)

    response = {
        'message': "New Block added",
        'index': block['index'],
        'transactions': block['transactions'],
        'proof': block['proof'],
        'previous_hash': block['previous_hash'],
    }
    return jsonify(response), 200


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()
    index = blockchain.new_transaction(
        values['sender'], values['recipient'], values['domain'], values['zoneHash'])
    response = {'message': f'Transaction will be added to Block {index}'}
    return jsonify(response), 201


@app.route('/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200


@app.route('/nodes/register', methods=['GET'])
def register_nodes():
    res = api.add('conn')
    h = res['Hash']

    def find():
        os.system("ipfs dht findprovs "+h+"> peers")
    t1 = threading.Thread(target=find)
    t1.start()
    time.sleep(10)
    lis = []
    with open("peers", "r") as f:
        _ = f.readline()
        for line in f:
            line.rstrip("\n")
            print(line)
            li = api.dht_findpeer(line[:-1])
            li = li['Responses'][0]['Addrs']
            for ele in li:
                if ele.split("/")[1] == "ip4":
                    a = ele.split("/")[2]
                    try:
                        response = request.get(
                            f'http://{a}:5000/chain', timeout=1)
                        if response.status_code == 200:
                            if a != "127.0.0.1":
                                lis.append(a)
                    except:
                        print("", end="")

    for i in lis:
        i = "http://"+i+":5000"
    nodes = lis
    print(nodes)
    if nodes is None:
        return "Error: Please supply a valid list of nodes", 400

    for node in nodes:
        blockchain.register_node(node)

    response = {
        'message': 'New nodes have been added',
        'total_nodes': list(blockchain.nodes),
    }
    return jsonify(response), 201


@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = blockchain.resolve_conflicts()

    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': blockchain.chain
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': blockchain.chain
        }

    return jsonify(response), 200


@app.route('/', methods=['GET'])
def serve():
    content = open("index.html").read()
    return Response(content, mimetype="text/html")


@app.route('/<path:path>')
def get_resource(path):
    complete_path = os.path.join(p, path)
    return send_file(complete_path)


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000,
                        type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port
    app.run(host='0.0.0.0', port=port)
