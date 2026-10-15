from validate_port import validate_ssh_port
from db_storage import  init_db, add_node


def register_node(node:dict):
    "a dict or json object would be input and we have to verify the items in it and insert them in DB if makes sense"
    name, address, port = node['name'], node['address'], node['port']
    # check if name & address are of Dtype str:
    if not isinstance(name, str) or not isinstance(address,str):
        raise ValueError("Name and address must be strings")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Node Can't be Empty")

    clean_address = address.strip()
    if not clean_address:
        raise ValueError("Node address cant eb Empty")

    # Now as name and address are done cleaning , next is check if IP and PORT is correct
    # for port we have function  and for IP address , i am not sure if its IPv4 ir IPv6
    # though IPv4 is 32 bit digit . 1byte each no. (set of such 4)
    validated_port = validate_ssh_port(port)

    # init DB
    init_db()
    # now save to DB
    node_id = add_node(clean_name, clean_address, validated_port)

    return {
    "id": node_id,
    "name": clean_name,
    "address": clean_address,
    "ssh_port": validated_port,
    "status": "not_checked"
}



if __name__ == "__main__":
    dummyDict = {
        "name":"debian Go",
        "address":"192.137.12.7",
        "port":22
    }
    print(register_node(dummyDict))
