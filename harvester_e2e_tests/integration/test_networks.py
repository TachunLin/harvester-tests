

import subprocess

from time import sleep
from datetime import datetime, timedelta

import pytest
import paramiko

pytest_plugins = [
    "harvester_e2e_tests.fixtures.api_client",
    'harvester_e2e_tests.fixtures.network',
    'harvester_e2e_tests.fixtures.vm',
]


@pytest.fixture(scope="session")
def client():
    client = paramiko.client.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    yield client
    client.close()


@pytest.fixture(scope='session')
def vlan_network(request, api_client):
    vlan_nic = request.config.getoption('--vlan-nic')
    vlan_id = request.config.getoption('--vlan-id')
    # don't create network if VLAN is not correctly specified
    if vlan_id == -1:
        return

    api_client.clusternetworks.create(vlan_nic)
    api_client.clusternetworks.create_config(vlan_nic, vlan_nic, vlan_nic)

    network_name = f'vlan-network-{vlan_id}'
    code, data = api_client.networks.create(network_name, vlan_id, cluster_network=vlan_nic)
    assert 201 == code, (
        f"Failed to create network-attachment-definition {network_name} with error {code}, {data}"
    )

    data['id'] = data['metadata']['name']
    yield data

    api_client.networks.delete(network_name)
    # api_client.clusternetworks.delete_config(vlan_nic)
    # api_client.clusternetworks.create(vlan_nic)


@pytest.fixture(scope='class')
def qcow2_image_url():
    base_url = "https://download.opensuse.org/repositories/Cloud:/Images:/Leap_15.1/images/"
    image_name = "openSUSE-Leap-15.1-OpenStack.x86_64.qcow2"
    return base_url + image_name


class TestBackendNetwork:

    @pytest.mark.networks_p1
    @pytest.mark.dependency(name="mgmt_network_connection")
    def test_mgmt_network_connection(self, api_client, request, client,
                                     unique_name, qcow2_image_url):
        """
        Manual test plan reference:
        https://harvester.github.io/tests/manual/network/validate-network-management-network/


        Steps:
        1. Create a new VM
        2. Make sure that the network is set to the management network with masquerade as the type
        3. Wait until the VM boot in running state
        4. Check can ping VM
        5. Check can SSH to VM
        """
        wait_timeout = request.config.getoption('--wait-timeout')
        client_ip = request.config.getoption('--endpoint').strip('https://')

        # self.create_image_url(api_client, 'opensuse', qcow2_image_url, wait_timeout)

        tcp_foward = "sudo sed -i 's/AllowTcpForwarding no/AllowTcpForwarding yes/g'"
        restart_ssh = "/etc/ssh/sshd_config;sudo systemctl restart sshd.service"
        open_tcp_forward_command = tcp_foward + restart_ssh
        self.ssh_client(client, client_ip, "rancher", "p@ssword",
                        open_tcp_forward_command, wait_timeout)

        spec = api_client.vms.Spec(1, 2)
        spec.user_data += "password: 123456\nchpasswd: { expire: False }\nssh_pwauth: True"
        unique_name = unique_name + "-mgmt"
        # Create VM
        spec.add_image('opensuse', "default/opensuse")
        code, data = api_client.vms.create(unique_name, spec)
        assert 201 == code, (f"Failed to create vm with error: {code}, {data}")

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Get VM interface ipAddresses
        code, data = api_client.vms.vm_instance(unique_name)
        interfaces_data = data['status']['interfaces']
        for interface in interfaces_data:
            ip_addresses = interface['ipAddresses']

        # Ping management ip address
        mgmt_ip = ip_addresses[0]
        ping_command = "ping -c 50 {0}".format(mgmt_ip)

        _stdout, _stderr = self.ssh_client(
            client, client_ip, "rancher", "p@ssword", ping_command, wait_timeout)

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("64 bytes from {0}".format(mgmt_ip)) > 0, (
            'Failed to ping VM management IP %s' % (mgmt_ip))

        # SSH to management ip address and execute command
        _stdout, _stderr = self.ssh_jumpstart(
            client, mgmt_ip, client_ip, "rancher", "p@ssword", "opensuse", "123456", "ls")

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("bin") == 0, (
            'Failed to ssh to VM management IP %s' % (mgmt_ip))

    @pytest.mark.networks_p1
    @pytest.mark.dependency(name="mgmt_vlan_network_connection")
    def test_vlan_network_connection(self, api_client, request, client, unique_name,
                                     qcow2_image_url, vlan_network):
        """
        Manual test plan reference:
        https://harvester.github.io/tests/manual/network/validate-network-external-vlan/


        Steps:
        1. Create an external VLAN network
        2. Create a new VM already with the vlan network
        3. Check can ping external VLAN IP
        4. Check can SSH to VM from external IP
        """
        wait_timeout = request.config.getoption('--wait-timeout')
        unique_name = unique_name + "-vlan"
        # self.create_image_url(api_client, 'opensuse', qcow2_image_url, 600)

        spec = api_client.vms.Spec(1, 2, mgmt_network=False)
        spec.user_data += "password: 123456\nchpasswd: { expire: False }\nssh_pwauth: True"

        # Create VM
        spec.add_image('opensuse', "default/opensuse")
        spec.add_network("default", vlan_network['id'])

        code, data = api_client.vms.create(unique_name, spec)
        assert 201 == code, (f"Failed to create vm with error: {code}, {data}")

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Get VM interface ipAddresses
        code, data = api_client.vms.vm_instance(unique_name)
        interfaces_data = data['status']['interfaces']
        for interface in interfaces_data:
            ip_addresses = interface['ipAddresses']

        vlan_ip = ip_addresses[0]

        # Ping management ip address
        command = "ping -c 3 {0}".format(vlan_ip)

        result = subprocess.check_output(command, shell=True, encoding="utf-8")

        assert result.find("64 bytes from {0}".format(vlan_ip)) > 0, (
            'Failed to ping VM management IP %s' % (vlan_ip))

        # SSH to vlan ip address and execute command
        _stdout, _stderr = self.ssh_client(
            client, vlan_ip, "opensuse", "123456", 'ls', wait_timeout)

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("bin") == 0, (
            'Failed to ssh to VM management IP %s' % (vlan_ip))

        # cleanup vm
        api_client.vms.delete(unique_name)

        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)

            if code == 404:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to delete VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

    @pytest.mark.networks_p1
    @pytest.mark.dependency(name="mgmt_vlan_network_connection")
    def test_reboot_vlan_connection(self, api_client, request, client, unique_name,
                                    qcow2_image_url, vlan_network):
        """
        Manual test plan reference:
        https://harvester.github.io/tests/manual/network/validate-network-external-vlan/


        Steps:
        1. Create an external VLAN network
        2. Create a new VM already with the vlan network
        3. Check can ping external VLAN IP
        4. Reboot VM
        5. Ping VM during reboot
        6. Check can't ping VM during reboot
        7. Check the VM should reboot
        8. Ping VM during after reboot
        9. Check can ping VM
        """
        wait_timeout = request.config.getoption('--wait-timeout')
        unique_name = unique_name + "-reboot-vlan"

        spec = api_client.vms.Spec(1, 2, mgmt_network=False)
        spec.user_data += "password: 123456\nchpasswd: { expire: False }\nssh_pwauth: True"

        # Create VM
        spec.add_image('opensuse', "default/opensuse")
        spec.add_network("default", vlan_network['id'])

        code, data = api_client.vms.create(unique_name, spec)
        assert 201 == code, (f"Failed to create vm with error: {code}, {data}")

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Get VM interface ipAddresses
        code, data = api_client.vms.vm_instance(unique_name)
        interfaces_data = data['status']['interfaces']
        for interface in interfaces_data:
            ip_addresses = interface['ipAddresses']

        vlan_ip = ip_addresses[0]

        # Ping management ip address
        command = "ping -c 3 {0}".format(vlan_ip)

        result = subprocess.check_output(command, shell=True, encoding="utf-8")

        assert result.find("64 bytes from {0}".format(vlan_ip)) > 0, (
            'Failed to ping VM vlan IP %s' % (vlan_ip))

        code, data = api_client.vms.restart(unique_name)
        assert 204 == code, (f"Failed to reboot vm with error: {code}, {data}")

        # Check VM start in Starting state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            if vm_fields[2] == 'Starting':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to restart VM {unique_name} in Starting status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        try:
            subprocess.check_output(command, shell=True, encoding="utf-8",
                                    stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            assert e.output.find("100% packet loss") > 0, (
                'Should be failed to ping VM vlan IP %s' % (vlan_ip))

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Get VM interface ipAddresses
        code, data = api_client.vms.vm_instance(unique_name)
        interfaces_data = data['status']['interfaces']
        for interface in interfaces_data:
            ip_addresses = interface['ipAddresses']

        vlan_ip = ip_addresses[0]

        # Ping management ip address
        command = "ping -c 3 {0}".format(vlan_ip)

        result = subprocess.check_output(command, shell=True, encoding="utf-8")

        # cleanup vm
        api_client.vms.delete(unique_name)

        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)

            if code == 404:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to delete VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

    @pytest.mark.networks_p1
    @pytest.mark.dependency(name="mgmt_vlan_network_connection")
    def test_mgmt_to_vlan_connection(self, api_client, request, client, unique_name,
                                     qcow2_image_url, vlan_network):
        """
        Manual test plan reference:
        https://harvester.github.io/tests/manual/network/edit-network-form-change-management-to-vlan/


        Steps:
        1. Create an external VLAN network
        2. Create a new VM
        3. Make sure that the network is set to the management network with masquerade as the type
        4. Wait until the VM boot in running state
        5. Edit VM and change management network to external VLAN with bridge type
        6. Check VM should save and reboot
        7. Check can ping the VM from an external network
        """

        wait_timeout = request.config.getoption('--wait-timeout')
        vlan_subnet_prefix = request.config.getoption('--vlan-cidr').rsplit('.', 1)[0]

        # self.create_image_url(api_client, 'opensuse', qcow2_image_url, wait_timeout)

        spec = api_client.vms.Spec(1, 2)
        spec.user_data += "password: 123456\nchpasswd: { expire: False }\nssh_pwauth: True"
        unique_name = unique_name + "-mgmt-vlan"
        # Create VM
        spec.add_image('opensuse', "default/opensuse")
        code, data = api_client.vms.create(unique_name, spec)
        assert 201 == code, (f"Failed to create vm with error: {code}, {data}")

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # code, data = api_client.vms.stop(unique_name)

        # get data from running VM and transfer to spec
        code, data = api_client.vms.get(unique_name)
        spec = spec.from_dict(data)

        # Switch to vlan network
        spec.mgmt_network = False
        spec.add_network("default", "default/" + vlan_network['id'])

        # Update VM spec
        code, data = api_client.vms.update(unique_name, spec)

        code, data = api_client.vms.restart(unique_name)

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Get VM interface ipAddresses
        code, data = api_client.vms.vm_instance(unique_name)
        interfaces_data = data['status']['interfaces']
        for interface in interfaces_data:
            ip_addresses = interface['ipAddresses']

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break

            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        endtime = datetime.now() + timedelta(seconds=wait_timeout)
        ip_addresses = []

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'interfaces' in data['status']:
                interfaces_data = data['status']['interfaces']
                ip_addresses = []
                ip_addresses.append(interfaces_data[0]['ipAddress'])

                if vlan_subnet_prefix in ip_addresses[0]:
                    break
                sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Ping management ip address
        vlan_ip = ip_addresses[0]
        command = "ping -c 3 {0}".format(vlan_ip)

        result = subprocess.check_output(command, shell=True, encoding="utf-8")

        assert result.find("64 bytes from {0}".format(vlan_ip)) > 0, (
            'Failed to ping VM management IP %s' % (vlan_ip))

        # SSH to vlan ip address and execute command
        _stdout, _stderr = self.ssh_client(
            client, vlan_ip, "opensuse", "123456", 'ls', wait_timeout)

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("bin") == 0, (
            'Failed to ssh to VM management IP %s' % (vlan_ip))

    @pytest.mark.networks_p1
    @pytest.mark.dependency(name="mgmt_vlan_network_connection")
    def test_vlan_to_mgmt_connection(self, api_client, request, client, unique_name,
                                     qcow2_image_url, vlan_network):
        """
        Manual test plan reference:
        https://harvester.github.io/tests/manual/network/edit-network-form-change-management-to-vlan/


        Steps:
        1. Create an external VLAN network
        2. Create a new VM
        3. Make sure that the network is set to the vlan network with bridge as the type
        4. Wait until the VM boot in running state
        5. Edit VM and change from external VLAN to management network
        6. Check VM should save and reboot
        7. Check can ping the VM on the management network
        """

        wait_timeout = request.config.getoption('--wait-timeout')
        client_ip = request.config.getoption('--endpoint').strip('https://')

        # self.create_image_url(api_client, 'opensuse', qcow2_image_url, wait_timeout)

        spec = api_client.vms.Spec(1, 2, mgmt_network=False)
        spec.user_data += "password: 123456\nchpasswd: { expire: False }\nssh_pwauth: True"
        unique_name = unique_name + "-vlan-mgmt"

        # Create VM
        spec.add_image('opensuse', "default/opensuse")
        spec.add_network("default", vlan_network['id'])

        code, data = api_client.vms.create(unique_name, spec)
        assert 201 == code, (f"Failed to create vm with error: {code}, {data}")

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # get data from running VM and transfer to spec
        code, data = api_client.vms.get(unique_name)
        spec = spec.from_dict(data)

        # Switch to vlan network
        spec.mgmt_network = True

        # Update VM spec
        code, data = api_client.vms.update(unique_name, spec)

        spec.delete_vlan_network(spec, vlan_network['id'])

        code, data = api_client.vms.update(unique_name, spec)

        code, data = api_client.vms.restart(unique_name)

        # Check VM start in running state
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.get(unique_name)
            vm_fields = data['metadata']['fields']

            assert 200 == code, (code, data)
            if vm_fields[2] == 'Running':
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to create VM {unique_name} in Running status, exceed 10 minutes\n"
                f"Still got {code} with {data}"
            )

        # Check until VM ip address exists
        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'ipAddress' in data['status']['interfaces'][0]:
                break

            sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        endtime = datetime.now() + timedelta(seconds=wait_timeout)
        ip_addresses = []

        while endtime > datetime.now():
            code, data = api_client.vms.vm_instance(unique_name)
            if 'interfaces' in data['status']:
                interfaces_data = data['status']['interfaces']
                ip_addresses = []
                ip_addresses.append(interfaces_data[0]['ipAddress'])

                if '10.52.0' in ip_addresses[0]:
                    break
                sleep(5)
        else:
            raise AssertionError(
                f"Failed to get VM {unique_name} IP address, exceed 10 minutes timed out\n"
                f"Still got {code} with {data}"
            )

        # Ping management ip address
        mgmt_ip = ip_addresses[0]
        ping_command = "ping -c 50 {0}".format(mgmt_ip)

        _stdout, _stderr = self.ssh_client(
            client, client_ip, "rancher", "p@ssword", ping_command, wait_timeout)

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("64 bytes from {0}".format(mgmt_ip)) > 0, (
            'Failed to ping VM management IP %s' % (mgmt_ip))

        sleep(30)

        # SSH to management ip address and execute command
        _stdout, _stderr = self.ssh_jumpstart(
            client, mgmt_ip, client_ip, "rancher", "p@ssword", "opensuse", "123456", "ls")

        stdout = _stdout.read().decode('ascii').strip("\n")

        assert stdout.find("bin") == 0, (
            'Failed to ssh to VM management IP %s' % (mgmt_ip))

    def ssh_client(self, client, dest_ip, username, password, command, timeout):
        client.connect(dest_ip, username=username, password=password, timeout=timeout)
        _stdin, _stdout, _stderr = client.exec_command(command)
        return _stdout, _stderr

    def ssh_jumpstart(self, client, dest_ip, client_ip, client_user, client_password,
                      dest_user, dest_password, command):
        client.connect(client_ip, username=client_user, password=client_password)

        client_transport = client.get_transport()
        dest_addr = (dest_ip, 22)
        client_addr = (client_ip, 22)
        client_channel = client_transport.open_channel("direct-tcpip", dest_addr, client_addr)

        jumpstart = paramiko.SSHClient()
        jumpstart.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jumpstart.connect(dest_ip, username=dest_user, password=dest_password, sock=client_channel)
        _stdin, _stdout, _stderr = jumpstart.exec_command(command)
        return _stdout, _stderr

    def create_image_url(self, api_client, display_name, image_url, wait_timeout):
        code, data = api_client.images.create_by_url(display_name, image_url)

        assert 201 == code, (code, data)
        image_spec = data.get('spec')

        assert display_name == image_spec.get('displayName')
        assert "download" == image_spec.get('sourceType')

        endtime = datetime.now() + timedelta(seconds=wait_timeout)

        while endtime > datetime.now():
            code, data = api_client.images.get(display_name)
            image_status = data.get('status', {})

            assert 200 == code, (code, data)
            if image_status.get('progress') == 100:
                break
            sleep(5)
        else:
            raise AssertionError(
                f"Failed to download image {display_name} with {wait_timeout} timed out\n"
                f"Still got {code} with {data}"
            )
