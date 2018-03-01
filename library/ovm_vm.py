#!/usr/bin/python

DOCUMENTATION = '''
---
module: ovm_vm
short_description: This module manages Virtual Machines inside Oracle-VM
description:
    - Module to manage Virtual Machine definitions inside Oracle-VM
author: 
    - Stephan Arts (@stephanarts)
    - Bas Schipper (@basschipper)
notes:
    - This module works with OVM 3.3 and 3.4
requirements:
    - requests package
options:
    state:
        description:
            - The intented state of the Oracle VM 
                - present = Create new Oracle VM
                - absent = Delete existing Oracle VM
                - start = Start existing Oracle VM
                - stop = Stop existing Oracle VM
                - restart = Restart existing Oracle VM
        required: True
        choices=["present","absent","start","stop","restart"]
    name:
        description:
            - The virtual-machine name, inside oracle-vm the vm-name is
            - not unique. It uses the vm-id as the unique identifier.
            - However, since this is not very useful for us mortals,
            - this module treats the vm-name and will return an error
            - if two virtual machines have the same name.
        required: True
    ovm_user:
        description:
            - The OVM admin-user used to connect to the OVM-Manager.
        required: True
    ovm_pass:
        description:
            - The password of the OVM admin-user.
        required: True
    ovm_host:
        description:
            - The base-url for Oracle-VM.
        default: https://127.0.0.1:7002
        required: False
    server_pool:
        description:
            - The Oracle-VM server-pool where to create/find the
            - Virtual Machine.
        required: True
    repository:
        description:
            - The Oracle-VM storage repository where to store the Oracle-VM
            - definition.
        required: True
    domain_type:
        description:
            - The domain type specifies the Virtual-Machine
            - virtualization mode.
        required: False
        default: "XEN_HVM"
        choices: [ XEN_HVM, XEN_HVM_PV_DRIVERS, XEN_PVM, LDOMS_PVM, UNKNOWN ]
    os_type:
        description:
            - The OS type specifies the operating system.
        required: False
        choices: [ "Oracle Linux 6" ]
'''

EXAMPLES = '''
- name: Create a Virtual Machine
  ovm_vm:
    name: 'host01'
    state: present
    ovm_host: https://127.0.0.1:7002
    ovm_user: 'admin'
    ovm_pass: 'password'
    server_pool: 'Pool1'
    repository: 'Repo1'
    cpu_count: 4
    memory: 4096
    boot_order:
      - PXE
      - DISK
    domain_type: XEN_PVM
    os_type: 'Oracle Linux 6'
    network_interfaces:
      - name: eth0
        mac: '00:00:00:00:00:00'
        network: 10.20.20.0
    disks:
      - slot: 0
        virtual_disk: host1_root
'''

RETURN = '''
name:
  description:
    - The virtual-machine name, inside oracle-vm the vm-name is
    - not unique. It uses the vm-id as the unique identifier.
    - However, since this is not very useful for us mortals,
    - this module treats the vm-name as a unique identifier and
    - will return an error if two VMs have the same name.
id:
  description:
    - The virtual-machine id, inside oracle-vm the vm id is
    - the unique identifier. This is the Id used when referencing
    - the vm from other resources.
'''

#==============================================================
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
try:
    import json
    HAS_JSON = True
except ImportError:
    HAS_JSON = False
try:
    import time
    HAS_TIME = True
except ImportError:
    HAS_TIME = False

from ansible.module_utils.basic import AnsibleModule

#==============================================================
def auth(ovm_user, ovm_pass):
    session = requests.Session()
    session.auth = (ovm_user, ovm_pass)
    session.verify = False
    session.headers.update({
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    })
    return session

#==============================================================
class OVMRestClient:

    def __init__(self, base_uri, session):
        self.session = session
        self.base_uri = base_uri

    def create(self, object_type, data):
        response = self.session.post(
            self.base_uri+'/'+object_type,
            data=json.dumps(data)
        )
        return response.json()

    def get(self, object_type, object_id):
        response = self.session.get(
            self.base_uri+'/'+object_type+'/'+object_id
        )
        return response.json()

    def delete(self, object_type, object_id):
        response = self.session.delete(
            self.base_uri+'/'+object_type+'/'+object_id
        )
        return response.json()

    def create_child(self, object_type, object_id, child_type, data):
        response = self.session.post(
            self.base_uri+'/'+object_type+'/'+object_id+'/'+child_type,
            data=json.dumps(data)
        )
        return response.json()

    def update_child(self, object_type, object_id, child_type, data={}):
        response = self.session.put(
            self.base_uri+'/'+object_type+'/'+object_id+'/'+child_type,
            data=json.dumps(data)
        )
        return response.json()

    def get_id_for_name(self, object_type, object_name):
        response = self.session.get(
            self.base_uri+'/'+object_type+'/id'
        )
        for element in response.json():
            if element['name'] == object_name:
                return element

        return None

    def get_ids(self, object_type):
        response = self.session.get(
            self.base_uri+'/'+object_type
        )

        return response.json()

    def monitor_job(self, job_id):
        while True:
            time.sleep(1)
            response = self.session.get(
                self.base_uri+'/Job/'+job_id)
            job = response.json()
            if job['summaryDone']:
                if job['jobRunState'] == 'FAILURE':
                    #raise Exception('Job failed: %s' % job['error'])
                    return {'changed': False, 'failed': True, 'msg': 'Job %s failed with: %s.' % (job['id']['value'], job['error'])}
                elif job['jobRunState'] == 'SUCCESS':
                    return {'changed': True, 'failed': False, 'resultId': job['resultId']}
                elif job['jobRunState'] == 'RUNNING':
                    continue
                else:
                    break


class OVMVmHelper:

    def __init__(self, client):
        self.client = client

    def get_id_for_name(self, name):
        return self.client.get_id_for_name('Vm', name)

    def create(self, data):
        result = self.client.create(
            'Vm',
            data)
        return self.client.monitor_job(result['id']['value'])
        # return {'changed': True, 'failed': False, 'instance': {}}

    def delete(self, name):
        vm_id = self.get_id_for_name(name)

        if vm_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a vm named %s.' % name } 

        result = self.client.delete(
            'Vm',
            vm_id['value'])

        return self.client.monitor_job(result['id']['value'])
        # return {'changed': True, 'failed': False, 'instance': {}}

    def create_virtualnic(self, name, network, mac_address):
        vm_id = self.get_id_for_name(name)

        if vm_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a vm named %s.' % name }

        network_id = self.client.get_id_for_name(
            'Network',
            network)

        if network_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a network named %s.' % network }

        result = self.client.create_child(
            'Vm',
            vm_id['value'],
            'VirtualNic',
            {
                'name': mac_address,
                'macAddress': mac_address,
                'networkId': network_id
            })
        
        return self.client.monitor_job(result['id']['value'])

    def create_diskmapping(self, name, slot, virtual_disk):
        vm_id = self.get_id_for_name(name)
        
        if vm_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a vm named %s.' % name }

        virtual_disk_id = self.client.get_id_for_name(
            'VirtualDisk',
            virtual_disk)
        
        if virtual_disk_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a virtual_disk named %s.' % virtual_disk }
        
        result = self.client.create_child(
            'Vm',
            vm_id['value'],
            'VmDiskMapping',
            {
                'diskTarget': slot,
                'virtualDiskId': virtual_disk_id
            })

        return self.client.monitor_job(result['id']['value'])

    def start(self, name):
        return self.state(name, 'start')

    def stop(self, name):
        return self.state(name, 'stop')

    def state(self, name, state):
        vm_id = self.get_id_for_name(name)

        if vm_id is None:
            return {'changed': False, 'failed': True, 'msg': 'Could not find a vm named %s.' % name }

        result = self.client.update_child(
            'Vm',
            vm_id['value'],
            state)

        return self.client.monitor_job(result['id']['value'])


def main():
    changed = False
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(
                choices=['present', 'absent', 'start', 'stop', 'restart', 'scale'],
                default='present',
                type='str'),
            name=dict(required=True, type='str'),
            ovm_user=dict(required=True, type='str'),
            ovm_pass=dict(required=True, type='str', no_log=True),
            ovm_host=dict(default='https://127.0.0.1:7002', type='str'),
            server_pool=dict(required=True, type='str'),
            repository=dict(required=True, type='str'),
            domain_type=dict(
                choices=[
                    'XEN_HVM',
                    'XEN_HVM_PV_DRIVERS',
                    'XEN_PVM',
                    'LDOMS_PVM',
                    'UNKNOWN'],
                default='XEN_HVM'),
            memory=dict(type='int', default=4096),
            memory_limit=dict(type='int', default=None),
            cpu_count=dict(type='int', default=2),
            cpu_count_limit=dict(type='int', default=None),
            cpu_priority=dict(type='int', default=100),
            cpu_utilization_cap=dict(type='int', default=100),
            high_availability=dict(type='bool', default=False),
            mouse_type=dict(
                choices=[
                    'USB_TABLET'],
                default='USB_TABLET'),
            keymap_name=dict(
                choices=[
                    'en-us'],
                default='en-us'),
            boot_order=dict(type='list'),
            os_type=dict(type='str'),
            network_install_path=dict(type='str'),
            start_policy=dict(type='str'),
            networks=dict(type='list'),
            disks=dict(type='list'),
            virtual_nics=dict(type='list'),
            disk_mappings=dict(type='list')
        )
    )

    if HAS_REQUESTS is False:
        module.fail_json(
            msg="ovm_vm module requires the 'requests' package")
    if HAS_JSON is False:
        module.fail_json(
            msg="ovm_vm module requires the 'json' package")
    if HAS_TIME is False:
        module.fail_json(
            msg="ovm_storage module requires the 'time' package")

    result = {'failed': False, 'changed': False}


    memory = module.params['memory']
    memory_limit = module.params['memory_limit']
    cpu_count = module.params['cpu_count']
    cpu_count_limit = module.params['cpu_count_limit']
    boot_order = module.params['boot_order']

    if memory%1024 != 0:
        module.fail_json(
            msg="memory must be a multitude of 1024")
    if memory_limit is None:
        memory_limit = memory
    else:
        if memory_limit < memory:
            module.fail_json(
                msg="memory_limit < memory")
        if memory_limit%1024 != 0:
            module.fail_json(
                msg="memory_limit must be a multitude of 1024")

    if cpu_count_limit is None:
        cpu_count_limit = cpu_count


    base_uri = module.params['ovm_host']+'/ovm/core/wsapi/rest'
    session = auth(module.params['ovm_user'], module.params['ovm_pass'])
    client = OVMRestClient(base_uri, session)
    vm_helper = OVMVmHelper(client)

    
    repository_id = client.get_id_for_name(
        'Repository',
        module.params['repository'])
    
    server_pool_id = client.get_id_for_name(
        'ServerPool',
        module.params['server_pool'])
    
    vm = vm_helper.get_id_for_name(module.params['name'])


    # VM already exists
    if vm:
        if module.params['state'] == 'absent':
            # destroy
            result = vm_helper.delete(module.params['name'])
        elif module.params['state'] == 'present':
            # reconfigure
            result = { 'failed': False }
        elif module.params['state'] in ['start', 'stop', 'restart']:
            # set powerstate
            result = vm_helper.state(module.params['name'], module.params['state'])
        else:
            assert False
    # VM doesn't exist
    else:
        if module.params['state'] in ['poweredon', 'poweredoff', 'present', 'restarted', 'suspended']:
            # create
            result = vm_helper.create({
                'repositoryId': repository_id,
                'serverPoolId': server_pool_id,
                'vmDomainType': module.params['domain_type'],
                'name': module.params['name'],
                'cpuCount': cpu_count,
                'cpuCountLimit': cpu_count_limit,
                'memory': memory,
                'memoryLimit': memory_limit,
                'cpuPriority': module.params['cpu_priority'],
                'cpuUtilizationCap': module.params['cpu_utilization_cap'],
                'highAvailability': module.params['high_availability'],
                'vmMouseType': module.params['mouse_type'],
                'keymapName': module.params['keymap_name'],
                'bootOrder': boot_order,
                'osType': module.params['os_type'],
                'networkInstallPath': module.params['network_install_path'],
                'vmStartPolicy': module.params['start_policy'], 
            })
            
            for virtual_nic in module.params['virtual_nics']:
                result = vm_helper.create_virtualnic(
                    module.params['name'], 
                    virtual_nic['network'],
                    virtual_nic['mac_address'])

            for disk_mapping in module.params['disk_mappings']:
                result = vm_helper.create_diskmapping(
                    module.params['name'],
                    disk_mapping['slot'],
                    disk_mapping['virtual_disk'])
  
            result = vm_helper.start(module.params['name'])

    if 'failed' not in result:
        result['failed'] = False

    if result['failed']:
        module.fail_json(**result)
    else:
        module.exit_json(**result)


if __name__ == '__main__':
    main()

