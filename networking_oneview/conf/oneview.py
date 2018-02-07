# Copyright 2018 Hewlett Packard Enterprise Development LP
# Copyright 2018 Universidade Federal de Campina Grande
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg

CONF = cfg.CONF

opts = [
    cfg.StrOpt('oneview_host',
               help='IP where OneView is available.'),
    cfg.StrOpt('username',
               help='OneView username to be used.'),
    cfg.StrOpt('password',
               secret=True,
               help='OneView password to be used.'),
    cfg.BoolOpt('allow_insecure_connections',
                default=False,
                help="Option to allow insecure connection with OneView."),
    cfg.StrOpt('tls_cacert_file',
               help="TLS File Path."),
    cfg.StrOpt('uplinkset_mappings',
               help='UplinkSets to be used.'),
    cfg.StrOpt('flat_net_mappings',
               help='Flat Networks on Oneview that are managed by Neutron.'),
    cfg.IntOpt('ov_refresh_interval',
               default=3600,
               help='Interval between periodic task executions in seconds.'),
    cfg.BoolOpt('developer_mode',
                default=False,
                help='Only set this option as true if under developer mode.')
]


def register_opts(conf):
    conf.register_opts(opts, group='oneview')