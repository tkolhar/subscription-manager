#
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#
from mock import Mock, patch

from stubs import StubUEP
import rhsm.connection as connection
from subscription_manager.managercli import RegisterCommand
from fixture import SubManFixture


class CliRegistrationTests(SubManFixture):

    def stub_persist(self, consumer):
        self.persisted_consumer = consumer
        return self.persisted_consumer

    def test_register_persists_consumer_cert(self):
        connection.UEPConnection = StubUEP

        # When
        cmd = RegisterCommand()

        self._inject_mock_invalid_consumer()

        cmd._persist_identity_cert = self.stub_persist
        cmd.facts.get_facts = Mock(return_value={'fact1': 'val1', 'fact2': 'val2'})
        cmd.facts.write_cache = Mock()

        cmd.main(['register', '--username=testuser1', '--password=password'])

        # Then
        self.assertEqual('dummy-consumer-uuid', self.persisted_consumer["uuid"])

    def test_installed_products_cache_written(self):
        connection.UEPConnection = StubUEP

        cmd = RegisterCommand()
        cmd._persist_identity_cert = self.stub_persist
        self._inject_mock_invalid_consumer()
        # Mock out facts and installed products:
        cmd.facts.get_facts = Mock(return_value={'fact1': 'val1', 'fact2': 'val2'})
        cmd.facts.write_cache = Mock()

        cmd.main(['register', '--username=testuser1', '--password=password'])

        # FIXME
        #self.assertTrue(mock_ipm_wc.call_count > 0)
