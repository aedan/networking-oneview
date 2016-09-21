import abc
import six
import utils
import json
import time
from neutron._i18n import _LW
from neutron._i18n import _LE
from neutron.plugins.ml2.drivers.oneview import common
from neutron.plugins.ml2.drivers.oneview import database_manager as db_manager
from oslo_config import cfg
from oslo_log import log


CONF = cfg.CONF

LOG = log.getLogger(__name__)

NETWORK_TYPE_FLAT = 'flat'


@six.add_metaclass(abc.ABCMeta)
class ResourceManager:
    def __init__(self, oneview_client):
        self.oneview_client = oneview_client


class Network(ResourceManager):
    def add_network_to_uplinksets(
        self, uplinksets_id_list, oneview_network_uri
    ):
        for uplinkset_id in uplinksets_id_list:
            uplinkset = self.oneview_client.uplink_sets.get(uplinkset_id)
            uplinkset['networkUris'].append(oneview_network_uri)
            self.oneview_client.uplink_sets.update(uplinkset)

    def create(
        self, session, neutron_network_dict, uplinkset_id_list,
        oneview_network_mapping_dict
    ):
        """Create a Network resource on OneView and populates the database.

        This function will create a Ethernet Network resource on OneView using
        data from Neutron Network and then populates a table on Neutron side
        mapping the Neutron Network with the OneView Ethernet Network.
        """

        neutron_network_id = neutron_network_dict.get('id')
        neutron_network_name = neutron_network_dict.get('name')
        neutron_network_seg_id = neutron_network_dict.get(
            'provider:segmentation_id'
        )

        physical_network = neutron_network_dict.get(
            'provider:physical_network'
        )

        provider_network = neutron_network_dict.get('provider:network_type')

        oneview_network_uuid = self.get_mapped_oneview_network_uuid(
            oneview_network_mapping_dict, provider_network, physical_network,
            neutron_network_name
        )

        if oneview_network_uuid is None:
            net_type = 'Tagged' if neutron_network_seg_id else 'Untagged'
            options = {
                'name': neutron_network_name,
                'ethernetNetworkType': net_type,
                'vlanId': neutron_network_seg_id,
                "purpose": "General",
                "smartLink": False,
                "privateNetwork": False,
            }
            if net_type == 'Tagged':
                options['vlanId'] = neutron_network_seg_id
            oneview_network = self.oneview_client.ethernet_networks.create(
                options
            )

            self.add_network_to_uplinksets(
                uplinkset_id_list, oneview_network.get('uri')
            )

        self.map_add_neutron_network_to_oneview_network_in_database(
            session, neutron_network_id,
            utils.id_from_uri(oneview_network.get('uri')),
            uplinkset_id_list
        )

    def get_mapped_oneview_network_uuid(
        self, oneview_network_mapping_dict, provider_network, physical_network,
        neutron_network_name
    ):
        if provider_network != NETWORK_TYPE_FLAT or physical_network is None:
            return None

        return oneview_network_mapping_dict.get(neutron_network_name)

    def map_add_neutron_network_to_oneview_network_in_database(
        self, session, neutron_network_id, oneview_network_id,
        uplinksets_id_list
    ):
        db_manager.insert_neutron_oneview_network(
            session, neutron_network_id, oneview_network_id
        )
        for uplinkset_id in uplinksets_id_list:
            db_manager.insert_oneview_network_uplinkset(
                session, oneview_network_id, uplinkset_id
            )

    def _remove_inconsistence_from_db(
        self, session, neutron_network_uuid, oneview_network_uuid
    ):
        db_manager.delete_neutron_oneview_network(
            session, neutron_network_uuid
        )
        db_manager.delete_oneview_network_uplinkset_by_uplinkset(
            session, oneview_network_uuid
        )

    def delete(
        self, session, neutron_network_dict, oneview_network_mapping_list
    ):
        neutron_network_id = neutron_network_dict.get('id')
        neutron_network_name = neutron_network_dict.get('name')
        neutron_network_seg_id = neutron_network_dict.get(
            'provider:segmentation_id'
        )
        physical_network = neutron_network_dict.get(
            'provider:physical_network'
        )
        provider_network = neutron_network_dict.get('provider:network_type')

        oneview_network_id = self.get_mapped_oneview_network_uuid(
            oneview_network_mapping_list, provider_network, physical_network,
            neutron_network_name
        )

        if oneview_network_id is None:
            neutron_oneview_network = db_manager.get_neutron_oneview_network(
                session, neutron_network_id
            )
            oneview_network_id = neutron_oneview_network.oneview_network_uuid
            self.oneview_client.ethernet_networks.delete(
                self.oneview_client.ethernet_networks.get(
                    neutron_oneview_network.oneview_network_uuid
                )
            )

            for port in db_manager.list_port_with_network(
                session, neutron_network_id
            ):
                neutron_oneview_port = db_manager.get_neutron_oneview_port(
                    session, port.id
                )
                sp_id = neutron_oneview_port.oneview_server_profile_uuid
                conn_id = neutron_oneview_port.oneview_connection_id

                self._remove_connection(sp_id, conn_id)

                db_manager.delete_neutron_oneview_port(session, port.id)

        self.map_remove_neutron_network_to_oneview_network_in_database(
            session, neutron_network_id, oneview_network_id
        )

    def _remove_connection(self, server_profile_id, connection_id):
        server_profile = self.oneview_client.server_profiles.get(
            server_profile_id
        )

        connections = []
        for connection in server_profile.get('connections'):
            if connection.get('id') != connection_id:
                connections.append(connection)

        server_profile_to_update = server_profile.copy()
        server_profile_to_update['connections'] = connections

        self.oneview_client.server_profile.update(
            resource=server_profile_to_update,
            id_or_uri=server_profile_to_update.get('uri')
        )

    def map_remove_neutron_network_to_oneview_network_in_database(
        self, session, neutron_network_id, oneview_network_id
    ):
        db_manager.delete_neutron_oneview_network(
            session, neutron_network_id
        )
        db_manager.delete_oneview_network_uplinkset_by_network(
            session, oneview_network_id
        )

    def update(self, session, neutron_network_id, new_network_name):
        neutron_oneview_network = db_manager.get_neutron_oneview_network(
            session, neutron_network_id
        )
        if neutron_oneview_network is None:
            return

        try:
            network = self.oneview_client.ethernet_networks.get(
                neutron_oneview_network.oneview_network_uuid
            )
            network['name'] = new_network_name
            self.oneview_client.ethernet_networks.update(network)
            # self.oneview_client.ethernet_network.update_name(
            #     neutron_oneview_network.oneview_network_uuid,
            #     new_network_name
            # )
        except:
            self._remove_inconsistence_from_db(
                session, neutron_network_id,
                neutron_oneview_network.oneview_network_uuid
            )
            LOG.warning(_LW("No mapped Network in Oneview"))


class Port(ResourceManager):
    def create(
        self, session, neutron_port_uuid, neutron_network_id, mac_address,
        local_link_information_dict
    ):
	
	switch_info_string = local_link_information_dict.get('switch_info')
        if not switch_info_string:
            LOG.warning(_LW(
                "Port %s local_link_information does not contain switch_info. Skipping."),
                neutron_port_uuid)
            return
	
        switch_info_string = switch_info_string.replace("'", '"')
        switch_info_dict = json.loads(switch_info_string)
	#@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
	#TODO extract string to dict function in delete port and create port
        server_hardware_uuid = switch_info_dict.get('server_hardware_uuid')
        if not server_hardware_uuid:
            LOG.warning(_LW(
                "Port %s switch_info does not contain server_hardware_uuid. Skipping."),
                neutron_port_uuid)
            return

        boot_priority = switch_info_dict.get('boot_priority')
        if not boot_priority:
            LOG.error(_LE(
                "Port %s switch_info does contains server_hardware_uuid but not boot_priority. Skipping."),
                neutron_port_uuid)
            raise ValueError("Port has server_hardware_uuid but not boot_priority")

        server_hardware = self.oneview_client.server_hardware.get(
            server_hardware_uuid
        )

        server_profile_uri = utils.id_from_uri(
            server_hardware.get('serverProfileUri')
       )

        neutron_oneview_network = db_manager.get_neutron_oneview_network(
            session, neutron_network_id
        )
	while True:
            print "#####################@@@@@@@@@@@@@@@@@@@@################%%%%"
            print self.get_server_hardware_power_lock_state(server_hardware_uuid)
	    if not self.get_server_hardware_power_lock_state(server_hardware_uuid):
	        break
	   
        previous_power_state = self.get_server_hardware_power_state(
            server_hardware_uuid
        )
	print neutron_network_id
	print neutron_oneview_network
	print "NETWORK #########################################################"
	print "NETWORK #########################################################"
        self.update_server_hardware_power_state(server_hardware_uuid, "Off")

	print "AKIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII111111111111111"
        connection_id = self._add_connection(
            server_profile_uri,
            self._generate_connection_port_for_mac(
                server_hardware, mac_address
            ),
            utils.uri_from_id(
                '/rest/ethernet-networks/',
                neutron_oneview_network.oneview_network_uuid
            ), boot_priority
        )
	print "AKIIIIIIIIIIIIIIIIIIIIIIIIIIIIII222222222222222222"
        db_manager.insert_neutron_oneview_port(
            session, neutron_port_uuid, server_profile_uri, connection_id
        )
	print "###+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++#"
        self.update_server_hardware_power_state(
            server_hardware_uuid, previous_power_state
        )
	print "++++++++++++++++++++++++++++++++++++++++++=================="

    def get_server_hardware_power_lock_state(self, server_hardware_id):
#       time.sleep(50)
        server_hardware_dict = self.oneview_client.server_hardware.get(
            server_hardware_id
        )
        return server_hardware_dict.get('powerLock')

    def get_server_hardware_power_state(self, server_hardware_id):
#	time.sleep(50)
        server_hardware_dict = self.oneview_client.server_hardware.get(
            server_hardware_id
        )
        return server_hardware_dict.get('powerState')

    def update_server_hardware_power_state(self, server_hardware_id, state):
            configuration = {
                "powerState": state,
                "powerControl": "MomentaryPress"
            }
#	    time.sleep(29)
            server_power = (
                self.oneview_client.server_hardware.update_power_state(
                    configuration, server_hardware_id
                )
            )

    def _generate_connection_port_for_mac(self, server_hardware, mac_address):
        port_info = self._get_connection_port_info(
            server_hardware, mac_address
        )

        return str(port_info.get('device_slot_location')) + " " +\
            str(port_info.get('device_slot_port_number')) + ":" +\
            str(port_info.get('physical_port_number')) + "-" +\
            str(port_info.get('virtual_port_function'))

    def _get_connection_port_info(self, server_hardware, mac_address):
        port_map = server_hardware.get('portMap')
        device_slots = port_map.get('deviceSlots')

        for device_slot in device_slots:
            physical_ports = device_slot.get('physicalPorts')
            for physical_port in physical_ports:
                virtual_ports = physical_port.get('virtualPorts')
                for virtual_port in virtual_ports:
                    mac = virtual_port.get('mac')
                    if mac == mac_address.upper():
                        info_dict = {
                            'virtual_port_function': virtual_port.get(
                                'portFunction'
                            ),
                            'physical_port_number': physical_port.get(
                                'portNumber'
                            ),
                            'device_slot_port_number': device_slot.get(
                                'slotNumber'
                            ),
                            'device_slot_location': device_slot.get(
                                'location'
                            ),
                        }
			print physical_port.get('portNumber')
                        return info_dict

    def _add_connection(
        self, server_profile_id, port_id, network_uri, boot_priority
    ):

        def get_next_connection_id(server_profile):
            next_id = 0
            for connection in server_profile.get('connections'):
                if connection.get('id') > next_id:
                    next_id = connection.get('id')
            return next_id + 1


        # TODO verify if server_profile.get('connections') is none - Rack server
        server_profile = self.oneview_client.server_profiles.get(
            server_profile_id
        ).copy()	
        
        existing_connections = [c for c in server_profile['connections'] if c['portId'] == port_id]
        for connection in existing_connections:
            server_profile['connections'].remove(connection)

	connection_id = get_next_connection_id(server_profile)

	server_profile['connections'].append({
            'portId': port_id,
            'networkUri': network_uri,
            'boot': {'priority': boot_priority},
            'functionType': 'Ethernet',
	    'id': connection_id
        })

        self.oneview_client.server_profiles.update(
            resource=server_profile,
            id_or_uri=server_profile.get('uri')
        )

        return connection_id

    def update(
        self, session, neutron_port_uuid, lli_dict, port_boot_priority,
        port_mac_address
    ):
        neutron_oneview_port = db_manager.get_neutron_oneview_port(
            session, neutron_port_uuid
        )
        server_hardware = self.oneview_client.server_hardware.get(
            common.server_hardware_from_local_link_information(lli_dict)
        )
        server_profile_uuid = utils.id_from_uri(
            server_hardware.get('serverProfileUri')
        )

        return self._update_connection(
            server_profile_uuid,
            neutron_oneview_port.oneview_connection_id,
            self._generate_connection_port_for_mac(
                server_hardware, port_mac_address
            ),
            port_boot_priority
        )

    def _update_connection(
        self, server_profile_id, connection_id, port_id, boot_priority
    ):
        server_profile = self.oneview_client.server_profiles.get(
            server_profile_id
        ).copy()

        for connection in server_profile.get('connections'):
            if int(connection.get('id')) == int(connection_id):
                connection['portId'] = port_id
                connection['boot'] = {'priority': boot_priority}

        self.oneview_client.server_profiles.update(
            resource=server_profile,
            id_or_uri=server_profile.get('uri')
        )

        return connection_id

    def delete(self, session, neutron_port_uuid, server_hardware_uuid):
        neutron_oneview_port = db_manager.get_neutron_oneview_port(
            session, neutron_port_uuid
        )
        server_hardware = self.oneview_client.server_hardware.get(
            server_hardware_uuid
        )
        while True:
            print "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%"
            print self.get_server_hardware_power_lock_state(server_hardware_uuid)
            if not self.get_server_hardware_power_lock_state(server_hardware_uuid):
                break

        previous_power_state = self.get_server_hardware_power_state(
            server_hardware_uuid
        )
        self.update_server_hardware_power_state(server_hardware_uuid, "Off")

        if neutron_oneview_port:
            self._delete_connection(
                neutron_oneview_port.oneview_server_profile_uuid,
                neutron_oneview_port.oneview_connection_id
            )
            db_manager.delete_neutron_oneview_port(session, neutron_port_uuid)

        self.update_server_hardware_power_state(
            server_hardware_uuid, previous_power_state
        )

    def _delete_connection(self, server_profile_id, connection_id):
        server_profile = self.oneview_client.server_profiles.get(
            server_profile_id
        ).copy()

        connections = []
        for connection in server_profile.get('connections'):
            if int(connection.get('id')) != int(connection_id):
                connections.append(connection)

        server_profile['connections'] = connections

        self.oneview_client.server_profiles.update(
            resource=server_profile,
            id_or_uri=server_profile.get('uri')
        )




class UplinkSet(ResourceManager):
    neutron_net_type_to_oneview_net_type = {
        'vxlan': 'Tagged',
        'vlan': 'Tagged',
        'flat': 'Untagged',
    }

    def filter_by_type(self, uplinkset_list, network_type):
        uplinkset_by_type = []
        if uplinkset_list is None or len(uplinkset_list) == 0:
            return uplinkset_by_type

        oneview_net_type = self.neutron_net_type_to_oneview_net_type.get(
            network_type
        )

        for uplinkset_uuid in uplinkset_list:
            uplinkset = self.oneview_client.uplink_sets.get(uplinkset_uuid)
            if uplinkset.get('ethernetNetworkType') == oneview_net_type:
                uplinkset_by_type.append(uplinkset_uuid)

        return uplinkset_by_type

    def remove_network(self, session, uplinkset_id, network_id):
        self.oneview_client.uplinkset.remove_network(
            uplinkset_id, network_id
        )
        db_manager.delete_oneview_network_uplinkset(
            session, uplinkset_id, network_id
        )

    def add_network(self, session, uplinkset_id, network_id):
        self.oneview_client.uplinkset.add_network(
            uplinkset_id, network_id
        )
        db_manager.insert_oneview_network_uplinkset(
            session, network_id, uplinkset_id
        )


class Client:
    def __init__(self, oneview_client):
        self.network = Network(oneview_client)
        self.port = Port(oneview_client)
        self.uplinkset = UplinkSet(oneview_client)
