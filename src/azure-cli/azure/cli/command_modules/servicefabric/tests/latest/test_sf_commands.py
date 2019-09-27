# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import unittest
import json
import logging
import os
import time
from azure.cli.core.util import CLIError
from azure.cli.testsdk import ScenarioTest, LiveScenarioTest, ResourceGroupPreparer

TEST_DIR = os.path.abspath(os.path.join(os.path.abspath(__file__), '..'))

logger = logging.getLogger(__name__)


def _create_keyvault(test, kwargs):
    kwargs.update({'policy_path': os.path.join(TEST_DIR, 'policy.json')})

    test.cmd('keyvault create --resource-group {rg} -n {kv_name} -l {loc} --enabled-for-deployment true --enabled-for-template-deployment true')
    test.cmd('keyvault certificate create --vault-name {kv_name} -n {cert_name} -p @"{policy_path}"')


def _create_cluster(test, kwargs):
    _create_keyvault(test, kwargs)

    while True:
        cert = test.cmd('keyvault certificate show --vault-name {kv_name} -n {cert_name}').get_output_in_json()
        if cert:
            break
    assert cert['sid'] is not None
    cert_secret_id = cert['sid']
    logger.error(cert_secret_id)
    kwargs.update({'cert_secret_id': cert_secret_id})

    test.cmd('az sf cluster create -g {rg} -n {cluster_name} -l {loc} --secret-identifier {cert_secret_id} --vm-password "{vm_password}" --cluster-size 3')
    timeout = time.time() + 900
    while True:
        cluster = test.cmd('az sf cluster show -g {rg} -n {cluster_name}').get_output_in_json()
        if cluster['provisioningState']:
            if cluster['provisioningState'] == 'Succeeded':
                return
            if cluster['provisioningState'] == 'Failed':
                raise CLIError("Cluster deployment was not succesful")

        if time.time() > timeout:
            raise CLIError("Cluster deployment timed out")
        if not test.in_recording:
            time.sleep(20)


def _wait_for_cluster_state_ready(test, kwargs):
    timeout = time.time() + 900
    while True:
        cluster = test.cmd('az sf cluster show -g {rg} -n {cluster_name}').get_output_in_json()

        if cluster['clusterState']:
            if cluster['clusterState'] == 'Ready':
                return

        if time.time() > timeout:
            raise CLIError("Cluster deployment timed out. cluster state is not 'Ready'. State: {}".format(cluster['ClusterState']))
        if not test.in_recording:
            time.sleep(20)


class ServiceFabricApplicationTests(ScenarioTest):
    def _app_type_test(self):
        self.cmd('az sf application-type list -g {rg} -n {cluster_name}',
                 checks=[self.check('length(value)', 0)])
        app_type = self.cmd('az sf application-type create -g {rg} -n {cluster_name} --application-type-name {app_type_name}',
                            checks=[self.check('provisioningState', 'Succeeded')]).get_output_in_json()
        self.cmd('az sf application-type show -g {rg} -n {cluster_name} --application-type-name {app_type_name}',
                 checks=[self.check('id', app_type['id'])])
        self.cmd('az sf application-type delete -g {rg} -n {cluster_name} --application-type-name {app_type_name}')

        # SystemExit 3 'not found'
        with self.assertRaisesRegexp(SystemExit, '3'):
            self.cmd('az sf application-type show -g {rg} -n {cluster_name} --application-type-name {app_type_name}')

    def _app_type_version_test(self):
        self.cmd('az sf application-type-version list -g {rg} -n {cluster_name} --application-type-name {app_type_name}',
                 checks=[self.check('length(value)', 0)])
        app_type_version = self.cmd('az sf application-type-version create -g {rg} -n {cluster_name} '
                                    '--application-type-name {app_type_name} --version {v1} --package-url {app_package_v1}',
                                    checks=[self.check('provisioningState', 'Succeeded')]).get_output_in_json()
        self.cmd('az sf application-type-version show -g {rg} -n {cluster_name} --application-type-name {app_type_name} --version {v1}',
                 checks=[self.check('id', app_type_version['id'])])
        self.cmd('az sf application-type-version delete -g {rg} -n {cluster_name} --application-type-name {app_type_name} --version {v1}')

        # SystemExit 3 'not found'
        with self.assertRaisesRegexp(SystemExit, '3'):
            self.cmd('az sf application-type-version show -g {rg} -n {cluster_name} --application-type-name {app_type_name} --version {v1}')

    def _app_service_test(self):
        self.cmd('az sf application list -g {rg} -n {cluster_name}',
                 checks=[self.check('length(value)', 0)])
        app = self.cmd('az sf application create -g {rg} -n {cluster_name} --application-name {app_name} '
                       '--application-type-name {app_type_name} --version {v1} --package-url {app_package_v1} '
                       '--application-parameters Mode=binary',
                       checks=[self.check('provisioningState', 'Succeeded')]).get_output_in_json()
        self.cmd('az sf application show -g {rg} -n {cluster_name} --application-name {app_name}',
                 checks=[self.check('id', app['id'])])

        service = self.cmd('az sf service create -g {rg} -n {cluster_name} --application-name {app_name} --stateless --instance-count -1 '
                           '--service-name "{app_name}~testService" --service-type {service_type} --partition-scheme-singleton',
                           checks=[self.check('provisioningState', 'Succeeded')]).get_output_in_json()

        self.cmd('az sf service show -g {rg} -n {cluster_name} --application-name {app_name} --service-name "{app_name}~testService"',
                 checks=[self.check('id', service['id'])])

        self.cmd('az sf application-type-version create -g {rg} -n {cluster_name} '
                 '--application-type-name {app_type_name} --version {v2} --package-url {app_package_v2}',
                 checks=[self.check('provisioningState', 'Succeeded')])

        self.cmd('az sf application update -g {rg} -n {cluster_name} --application-name {app_name} --application-type-version {v2} '
                 '--application-parameters Mode=decimal --health-check-stable-duration 0 --health-check-wait-duration 0 --health-check-retry-timeout 0 '
                 '--upgrade-domain-timeout 5000 --upgrade-timeout 7000 --failure-action Rollback --upgrade-replica-set-check-timeout 300 --force-restart',
                 checks=[self.check('provisioningState', 'Succeeded')])
        self.cmd('az sf application show -g {rg} -n {cluster_name} --application-name {app_name}',
                 checks=[self.check('provisioningState', 'Succeeded'),
                         self.check('typeVersion', '{v2}'),
                         self.check('parameters.Mode', 'decimal'),
                         self.check('upgradePolicy.forceRestart', True),
                         self.check('upgradePolicy.upgradeReplicaSetCheckTimeout', '00:05:00'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.healthCheckRetryTimeout', '00:00:00'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.healthCheckWaitDuration', '00:00:00'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.healthCheckStableDuration', '00:00:00'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.upgradeTimeout', '01:56:40'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.upgradeDomainTimeout', '01:23:20'),
                         self.check('upgradePolicy.rollingUpgradeMonitoringPolicy.failureAction', 'Rollback')])

        self.cmd('az sf application update -g {rg} -n {cluster_name} --application-name {app_name} --minimum-nodes 1 --maximum-nodes 3',
                 checks=[self.check('provisioningState', 'Succeeded')])
        self.cmd('az sf application show -g {rg} -n {cluster_name} --application-name {app_name}',
                 checks=[self.check('provisioningState', 'Succeeded'),
                         self.check('minimumNodes', 1),
                         self.check('maximumNodes', 3)])

        self.cmd('az sf application delete -g {rg} -n {cluster_name} --application-name {app_name}')
        self.cmd('az sf application-type delete -g {rg} -n {cluster_name} --application-type-name {app_type_name}')

        # SystemExit 3 'not found'
        with self.assertRaisesRegexp(SystemExit, '3'):
            self.cmd('az sf application show -g {rg} -n {cluster_name} --application-name {app_name}')

    @ResourceGroupPreparer()
    def test_application(self):
        self.kwargs.update({
            'kv_name': self.create_random_name('sfrp-cli-kv-', 24),
            'loc': 'westus',
            'cert_name': self.create_random_name('sfrp-cli-', 24),
            'cluster_name': self.create_random_name('sfrp-cli-', 24),
            'vm_password': self.create_random_name('Pass@', 9),
            'app_type_name': 'CalcServiceApp',
            'v1': '1.0',
            'app_package_v1': 'https://sfrpserviceclienttesting.blob.core.windows.net/test-apps/CalcApp_1.0.sfpkg',
            'v2': '1.1',
            'app_package_v2': 'https://sfrpserviceclienttesting.blob.core.windows.net/test-apps/CalcApp_1.1.sfpkg',
            'app_name': self.create_random_name('testApp', 11),
            'service_type': 'CalcServiceType'
        })

        _create_cluster(self, self.kwargs)
        self._app_type_test()
        self._app_type_version_test()
        self._app_service_test()


class ServiceFabricApplicationTests(ScenarioTest):
    @ResourceGroupPreparer()
    def test_node_type(self):
        self.kwargs.update({
            'kv_name': self.create_random_name('sfrp-cli-kv-', 24),
            'loc': 'westus',
            'cert_name': self.create_random_name('sfrp-cli-', 24),
            'cluster_name': self.create_random_name('sfrp-cli-', 24),
            'vm_password': self.create_random_name('Pass@', 9),
        })
        _create_cluster(self, self.kwargs)
        _wait_for_cluster_state_ready(self, self.kwargs)

        self.cmd('az sf cluster node-type add -g {rg} -n {cluster_name} --node-type nt2 --capacity 5 --vm-user-name admintest '
                 '--vm-password {vm_password} --durability-level Gold --vm-sku Standard_D15_v2',
                 checks=[self.check('provisioningState', 'Succeeded'),
                         self.check('length(nodeTypes)', 2),
                         self.check('nodeTypes[1].name', 'nt2'),
                         self.check('nodeTypes[1].vmInstanceCount', 5),
                         self.check('nodeTypes[1].durabilityLevel', 'Gold')])


if __name__ == '__main__':
    unittest.main()
