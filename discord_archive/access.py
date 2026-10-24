"""Explain private server access without advertising unreachable HTTP URLs."""
import ipaddress
import json
import shutil
import subprocess

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
    ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10'])


def private_addresses(interfaces):
    addresses=[]
    for interface in interfaces:
        for row in interface.get('addr_info',[]):
            try: value=ipaddress.ip_address(row.get('local',''))
            except ValueError: continue
            if value.version==4 and any(value in network for network in PRIVATE_NETWORKS):
                if str(value) not in addresses: addresses.append(str(value))
    return addresses


def linux_access(host='127.0.0.1', port=8765):
    addresses=[]
    try:
        result=subprocess.run(['ip','-j','-4','address','show','up'],capture_output=True,text=True,timeout=3)
        if result.returncode==0: addresses=private_addresses(json.loads(result.stdout))
    except (OSError,ValueError,subprocess.SubprocessError): pass
    try: loopback=host=='localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError: loopback=False
    return {'server_addresses':addresses,'listen_host':host,'listen_port':port,
        'loopback_only':loopback,
        'tailscale_installed':bool(shutil.which('tailscale')),
        'tunnel_workbench':'http://127.0.0.1:18765',
        'tunnel_desktop':'http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale'}
