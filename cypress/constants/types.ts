// harvester
export const HCI = {
  VM:                 'kubevirt.io.virtualmachine',
  VMI:                'kubevirt.io.virtualmachineinstance',
  VMIM:               'kubevirt.io.virtualmachineinstancemigration',
  VM_TEMPLATE:        'harvesterhci.io.virtualmachinetemplate',
  VM_VERSION:         'harvesterhci.io.virtualmachinetemplateversion',
  IMAGE:              'harvesterhci.io.virtualmachineimage',
  SSH:                'harvesterhci.io.keypair',
  VOLUME:             'harvesterhci.io.volume',
  USER:               'harvesterhci.io.user',
  SETTING:            'harvesterhci.io.setting',
  UPGRADE:            'harvesterhci.io.upgrade',
  BACKUP:             'harvesterhci.io.virtualmachinebackup',
  RESTORE:            'harvesterhci.io.virtualmachinerestore',
  NODE_NETWORK:       'network.harvesterhci.io.nodenetwork',
  CLUSTER_NETWORK:    'network.harvesterhci.io.clusternetwork',
  SUPPORT_BUNDLE:     'harvesterhci.io.supportbundle',
  NETWORK_ATTACHMENT: 'harvesterhci.io.networkattachmentdefinition',
  CLUSTER:            'harvesterhci.io.management.cluster',
  DASHBOARD:          'harvesterhci.io.dashboard',
  BLOCK_DEVICE:       'harvesterhci.io.blockdevice',
  CLOUD_TEMPLATE:     'harvesterhci.io.cloudtemplate',
  HOST:               'harvesterhci.io.host',
  VERSION:            'harvesterhci.io.version',
  MANAGED_CHART:      'harvesterhci.io.managedchart',
  STORAGE_CLASS:      'harvesterhci.io.storage',
};

export const NETWORK_ATTACHMENT = 'k8s.cni.cncf.io.networkattachmentdefinition';
export const PVC = 'persistentvolumeclaim';
export const STORAGE_CLASS = 'storage.k8s.io.storageclasse';
