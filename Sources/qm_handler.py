# encoding: utf-8

import sys
from workflow import Workflow3, Variables
from workflow.util import run_command

import re
import os
import argparse

reload(sys)
sys.setdefaultencoding('utf8')

# some definitions
    
VMTYPE_QEMU = "qemu"
VMTYPE_LXC = "lxc"

MODE_STATUS = 1
MODE_MACHINE = 2
MODE_TYPE = 4

# Note: it would be more elegant to use the Proxmox-API to list, start and stop
# machines, but this would be approx 20% slower than using ssh and the cli-tools
# (at least on my machine), and would rely on some more external packages.
#
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
ssh_cmd_list[VMTYPE_QEMU] = "ssh %s 'qm list'"   # ssh_destination
ssh_cmd_list[VMTYPE_LXC] = "ssh %s 'pct list'"   # ssh_destination

# for use with % (action, vm_id)
# e.g. qm start 113
ssh_cmd_action = {}
ssh_cmd_action[VMTYPE_QEMU] = "ssh %s 'qm %s %s'"        # (action, vm_id)
ssh_cmd_action[VMTYPE_LXC] = "ssh %s 'pct %s %s'"        # (action, vm_id)

proxmox_user = os.environ['PROXMOX_USER']
proxmox_host = os.environ['PROXMOX_HOST']
ssh_port = os.environ['SSH_PORT']

ssh_destination = "-p %s %s@%s" % (ssh_port, proxmox_user, proxmox_host)
    
excluded_vm_ids = os.environ['EXCLUDED_VMS']
excluded_vm_ids = [elem.strip() for elem in excluded_vm_ids.split(",")]

def prepare_output_result_for_regex(result):
    """Prepares the cli-output."""
    result_text = result.decode("utf-8")
    result_list = result_text.splitlines()
    result_list.pop(0)

    return result_list

def get_cli_output(vm_type, ssh_destination):
    command = ssh_cmd_list[vm_type] % ssh_destination
    log.debug(command)
    result = run_command([command], shell=True)
    
    cli_output = prepare_output_result_for_regex(result)
    
    return cli_output


def get_vm_items():

    list_of_qemus = get_cli_output(VMTYPE_QEMU, ssh_destination)
    list_of_lxcs = get_cli_output(VMTYPE_LXC, ssh_destination)
    
    qemus = get_vms(list_of_qemus, VMTYPE_QEMU)
    lxcs = get_vms(list_of_lxcs, VMTYPE_LXC)

    return qemus + lxcs

def append_to_resultlist(res_list, vm_type, vm_id, vm_name, vm_status):
    if vm_id not in excluded_vm_ids:
        action = 'stop' if vm_status == 'running' else 'start'
        command = ssh_cmd_action[vm_type] % (ssh_destination, action, vm_id)

        res_list.append({
                        'id': vm_id.encode('utf8'),
                        'title': vm_name.encode('utf8'),
                        'status': vm_status.encode('utf8'),
                        'type': vm_type.encode('utf8'),
                        'action': action.encode('utf8'),
                        'subtitle': ("%s ist currently %s" % (vm_id, vm_status)).encode('utf8'),
                        'arg': command.encode('utf8')
                    })


def get_vms(list_of_machines, machine_type):
    
    resultlist = []

    if machine_type == VMTYPE_QEMU:
        for line in list_of_machines:
            m = re.search(r'\s*(\d+)\s+([^\s]+)\s+(\w+).*', line)
            vm_id = m.group(1)
            vm_name = m.group(2)
            vm_status = m.group(3)

            append_to_resultlist(resultlist, VMTYPE_QEMU, vm_id, vm_name, vm_status)

    elif machine_type == VMTYPE_LXC:
        for line in list_of_machines:
            m = re.search(r'^\s*(\d+)\s+(\w+)\s+(\w+|\s+)\s+([^\s]+)\s*$', line)
            vm_id = m.group(1)
            vm_name = m.group(4)
            vm_status = m.group(2)

            append_to_resultlist(resultlist, VMTYPE_LXC, vm_id, vm_name, vm_status)

    return resultlist

def sort_key_for_entries(entry):
    return entry['id']

def do_action(query):
    """Perform the start/stop-action on the selected machine."""
    log.debug("query: " + query)
    exit = run_command([query], shell=True)
    
    # set variables for notification output
    v = Variables()
    if exit == "":
        v['WF_RESULT'] = u"Succeeded"
    else:
        v['WF_RESULT'] = u"Failed"
    
    v['WF_ACTION'] = query.encode('utf8')
    print(v)
    
    wf.clear_cache()

def do_list(resultlist, mode):
    """List all machines based on the given mode."""
    resultlist.sort(key=sort_key_for_entries)
    
    for res in resultlist:
        id = res['id']
        title = res['title']
        subtitle = res['subtitle']
        command = res['arg']
        valid = True
        
        if mode == MODE_MACHINE:
            match = title
        elif mode == MODE_STATUS:
            match = res['action']
        elif mode == MODE_TYPE:
            match = res['type']
            
        icon = "%s_%s.png" % (res['type'], res['status'])
        
        wf.add_item(title=title, subtitle=subtitle, valid=valid, arg=command, match=match, uid=id, icon=icon)

    if mode == MODE_MACHINE:
        wf.warn_empty('No matching machines', 'Try a different query')
    elif mode == MODE_STATUS:
        wf.warn_empty('No machine found', "Try 'start' or 'stop' as argument")
    elif mode == MODE_TYPE:
        log.debug("###################WARM_EMPTY")
        wf.warn_empty('No matching type', 'Try either qemu or lxc.')
    
    wf.send_feedback()

def get_python27():
    PYTHON_PATH = os.getenv('PYTHON_PATH')
    if PYTHON_PATH is not None: 
        paths = PYTHON_PATH.split(":")
        for path in paths:
            python27 = path + "/python"
            if os.path.isfile(python27):
                return python27
    return None

def main(wf):
    """Run Script Filter."""
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'machine', 'type', 'set'))
    parser.add_argument('query', nargs='?')
    args = parser.parse_args(wf.args)
    
    log.debug('action=%r, query=%r', args.action, args.query)
    
    if args.action == 'set':
        return do_action(args.query)
    
    resultlist = wf.cached_data('resultlist', get_vm_items)

    if args.action == 'status':
        return do_list(resultlist, MODE_STATUS)
    if args.action == 'machine':
        return do_list(resultlist, MODE_MACHINE)
    if args.action == 'type':
        return do_list(resultlist, MODE_TYPE)
    
    return

if __name__ == u'__main__':
    wf = Workflow3()
    log = wf.logger
    sys.exit(wf.run(main))