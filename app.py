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
from werkzeug import secure_filename
import objectpath as op


def h(block):
    block_string = json.dumps(block, sort_keys=True).encode()
    return hashlib.sha256(block_string).hexdigest()


class Blockchain:
    def __init__(self, data):
        self.chain = data
        self.current_transactions = []
        self.nodes = set()
        if len(data) is 0:
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

    def new_transaction(self, transaction):

        self.current_transactions.append(transaction)
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


with open("chain.json", "r") as read_file:
    data = json.load(read_file)
app = Flask(__name__, static_folder=os.getcwd())
p = os.getcwd()
blockchain = Blockchain(data)
api = ipfsapi.connect('127.0.0.1', 5001)
Dp = 5


@app.route('/mine', methods=['GET'])
def mine():
    global Dp
    last_block = blockchain.last_block
    proof = blockchain.proof_of_work(last_block)
    Dp += 1
    ipfsid = api.id()['ID']
    blockchain.new_transaction({
        'miner': ipfsid,
        'credits': Dp,
    })
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
    index = blockchain.new_transaction({
        'senderID': values['sender'],
        'buyerID': values['recipient'],
        'domain': values['domain'],
        'zoneHash': values['zoneHash']
    })
    response = {'message': f'Transaction will be added to Block {index}'}
    return jsonify(response), 201


@app.route('/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200


@app.route('/me', methods=['GET'])
def info():
    chain = str(blockchain.chain)
    dr = chain.count('domain')
    response = {
        'credits': Dp,
        'pc': len(blockchain.nodes),
        'dr': dr
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


@app.route('/assets/<path:path>')
def get_resource(path):
    complete_path = os.path.join(p+"/assets", path)
    return send_file(complete_path)


@app.errorhandler(404)
def page_not_found(e):
    return send_file(os.path.join(p+"/assets", "404.jpg")), 404


def query(domain):
    tree_obj = op.Tree(blockchain.chain)
    blocks=list(tree_obj.execute('$..transactions'))
    blocks.pop(0)
    for block in blocks:
        try:    
            if str(block['domain']) == str(domain):
                return False
        except:
            print(end='')
    return True


@app.route('/reg', methods=['POST'])
def reg():
    global Dp
    if request.method == 'POST':
        values = dict(request.form)
        domain = values['Domain']
        if query(domain) is True:
            zf = request.files['Zonefile']
            values['name'] = zf.filename
            zf.save(os.path.join('zones', secure_filename(zf.filename)))
            resp = api.add(os.path.join('zones', secure_filename(zf.filename)))
            index = blockchain.new_transaction({
                'buyerID': api.id()['ID'],
                'domain': domain,
                'zoneHash': resp['Hash']
            })
            Dp -= 1
            return "Domain: "+domain+" Is Registered in BNS will be added to Block "+str(index), 200
        else:
            return "Domain Already exist", 200


@app.route('/trans', methods=['POST'])
def trans():
    global Dp
    if request.method == 'POST':
        values = dict(request.form)
        domain = values['Domain']
        if query(domain) is True:
            zf = request.files['Zonefile']
            values['name'] = zf.filename
            zf.save(os.path.join('zones', secure_filename(zf.filename)))
            resp = api.add(os.path.join('zones', secure_filename(zf.filename)))
            index = blockchain.new_transaction({
                'senderID': values['sender'],
                'buyerID': values['reciver'],
                'domain': domain,
                'zoneHash': resp['Hash']
            })
            Dp -= 1
            return "Domain: "+domain+" Is Registered in BNS will be added to Block "+str(index), 200
        else:
            return "Domain Already exist", 200


@app.route("/site-map")
def site_map():
    resp = {}
    for rule in app.url_map.iter_rules():
        temp = dict.fromkeys(rule.methods, '')
        try:
            temp.pop("OPTIONS")
            temp.pop("HEAD")
        except:
            print()
        resp[str(rule)] = temp
    return jsonify(resp), 200


@app.route("/save")
def saveChain():
    with open("chain.json", "w") as write_file:
        json.dump(blockchain.chain, write_file)
    response = {
        'message': 'Blockchain is saved locally'
    }
    return jsonify(response), 200


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000,
                        type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port
    app.run(host='0.0.0.0', port=port)
