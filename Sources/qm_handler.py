# encoding: utf-8

import sys
from workflow import Workflow3

import subprocess
import re
import os
from enum import Enum

reload(sys)
sys.setdefaultencoding('utf8')

# some definitions

class VMTYPE(Enum):
    VM = 1
    LXC = 2

# typical output from cmd call of qm ...
# 
#       VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
#        100 firewall             running    2048              10.00 1294
#        101 wireguard            running    1024               4.00 15410
#        102 manjaro              running    4096              32.00 22267
#        103 fedora               stopped    8192              32.00 0
#        104 debian               running    4096              32.00 12011
#        900 firewall-test        stopped    2048              10.00 0
# 
# ... and from pct:
#
# VMID       Status     Lock         Name
# 105        running                 mycontainer
# 107        stopped                 lxc123

# for use with % ssh_destination
# e.g. ssh user@proxmoxhost -p port 'pct list'
ssh_cmd_list = {}
ssh_cmd_list[VMTYPE.VM] = "ssh %s 'qm list'"     # ssh_destination
ssh_cmd_list[VMTYPE.LXC] = "ssh %s 'pct list'"   # ssh_destination

# for use with % (action, vm_id)
# e.g. qm start 113
ssh_cmd_action = {}
ssh_cmd_action[VMTYPE.VM] = "qm %s %s"          # (action, vm_id)
ssh_cmd_action[VMTYPE.LXC] = "pct %s %s"        # (action, vm_id)

proxmox_user = os.environ['PROXMOX_USER']
proxmox_host = os.environ['PROXMOX_HOST']
ssh_port = os.environ['SSH_PORT']

ssh_destination = "-p %s %s@%s" % (ssh_port, proxmox_user, proxmox_host)
    
excluded_vm_ids = os.environ['EXCLUDED_VMS']
excluded_vm_ids = [elem.strip() for elem in excluded_vm_ids.split(",")]


def prepare_output_result_for_regex(result):
    result_text = result.decode("utf-8")
    result_list = result_text.splitlines()
    result_list.pop(0)

    return result_list

def get_cli_output(vm_type, ssh_destination):
    command = ssh_cmd_list[vm_type] % ssh_destination        
    result = subprocess.check_output(command, shell=True)
    
    cli_output = prepare_output_result_for_regex(result)
    
    return cli_output


def get_vm_items():
    list_of_vms = get_cli_output(VMTYPE.VM, ssh_destination)
    list_of_lxc = get_cli_output(VMTYPE.LXC, ssh_destination)
    entries = get_vms(list_of_vms=list_of_vms, list_of_lxc=list_of_lxc)

    return entries

def append_to_resultlist(res_list, vm_type, vm_id, vm_name, vm_status):
    if vm_id not in excluded_vm_ids:
        action = 'stop' if vm_status == 'running' else 'start'
        command = ssh_cmd_action[vm_type] % (action, vm_id)

        res_list.append({
                        'uid': vm_id.encode('utf8'),
                        'title': vm_name.encode('utf8'),
                        'subtitle': ("%s ist currently %s" % (vm_id, vm_status)).encode('utf8'),
                        'match': action.encode('utf8'),
                        'arg': command.encode('utf8')
                    })

def get_vms(list_of_vms=None, list_of_lxc=None):
    
    resultlist = []

    if list_of_vms is not None:
        for line in list_of_vms:
            m = re.search(r'\s*(\d+)\s+([^\s]+)\s+(\w+).*', line)
            vm_id = m.group(1)
            vm_name = m.group(2)
            vm_status = m.group(3)

            append_to_resultlist(resultlist, VMTYPE.VM, vm_id, vm_name, vm_status)
    
    if list_of_lxc is not None:
        for line in list_of_lxc:
            m = re.search(r'^\s*(\d+)\s+(\w+)\s+(\w+|\s+)\s+([^\s]+)\s*$', line)
            vm_id = m.group(1)
            vm_name = m.group(4)
            vm_status = m.group(2)

            append_to_resultlist(resultlist, VMTYPE.LXC, vm_id, vm_name, vm_status)

    return resultlist


def search_key(entries):
    elements = []
    elements.append(entries['match'])
    return u' '.join(elements)

def sort_key_for_entries(entry):
    return entry['uid']

def main(wf):
    
    if len(wf.args):
        query = wf.args[0]
    else:
        query = None

    wf.clear_session_cache()
    entries = wf.cached_data('entries', get_vm_items, session=True)
    
    if query:
        entries = wf.filter(query, entries, key=search_key)

    if not entries:
        wf.add_item('No matches')
        wf.send_feedback()
        return 0

    entries.sort(key=sort_key_for_entries)
    
    for entry in entries:
        wf.add_item(
            title = entry['title'],
            subtitle = entry['subtitle'], 
            uid = entry['uid'],
            match = entry['match'],
            arg = entry['arg'],
            valid = True
        )

    wf.send_feedback()
    return

if __name__ == u'__main__':
    wf = Workflow3()
    sys.exit(wf.run(main))