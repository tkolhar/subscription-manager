#
# Copyright (c) 2012 Red Hat, Inc.
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
import sys
import unittest

import certdata
import fixture

from rct.cert_commands import CatCertCommand
from rct.printing import xstr
from rhsm.certificate import create_from_pem

from stubs import MockStdout, MockStderr


class PrintingTests(unittest.TestCase):

    def test_xstr(self):
        self.assertEquals("", xstr(None))
        self.assertEquals("1", xstr(1))
        self.assertEquals("JarJar", xstr("JarJar"))


class CatCertCommandStub(CatCertCommand):
    """
    A testing CatCertCommand that allows bypassing
    the loading of a certificate file.
    """
    def __init__(self, cert_pem):
        CatCertCommand.__init__(self)
        self.cert = create_from_pem(cert_pem)

    def _validate_options(self):
        # Disable validation
        pass

    def _create_cert(self):
        return self.cert


class CatCertCommandTests(fixture.SubManFixture):

    def setUp(self):
        super(CatCertCommandTests, self).setUp()
        self.mock_stdout = MockStdout()
        self.mock_stderr = MockStderr()
        sys.stdout = self.mock_stdout
        sys.stderr = self.mock_stderr

    def _restore_stdout(self):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def tearDown(self):
        super(CatCertCommandTests, self).tearDown()
        self._restore_stdout()

    def test_omit_content_list(self):
        command = CatCertCommandStub(certdata.ENTITLEMENT_CERT_V1_0)
        command.main(["not_used.pem", "--no-content"])
        cert_output = self.mock_stdout.buffer
        self.assertTrue(cert_output.find("Content:\n") == -1,
                        "Content was not excluded from the output.")

    def test_omit_product_list(self):
        command = CatCertCommandStub(certdata.ENTITLEMENT_CERT_V1_0)
        command.main(["not_used.pem", "--no-products"])
        cert_output = self.mock_stdout.buffer
        self.assertTrue(cert_output.find("Product:\n") == -1,
                        "Products were not excluded from the output.")

    def test_cert_v1_cat(self):
        command = CatCertCommandStub(certdata.ENTITLEMENT_CERT_V1_0)
        command.main(['will_use_stub'])

        cert_output = self.mock_stdout.buffer
        self.assert_string_equals(certdata.ENTITLEMENT_CERT_V1_0_OUTPUT, cert_output)

    def test_cert_v3_cat(self):
        command = CatCertCommandStub(certdata.ENTITLEMENT_CERT_V3_0)
        command.main(['will_use_stub'])

        cert_output = self.mock_stdout.buffer
        self.assert_string_equals(certdata.ENTITLEMENT_CERT_V3_0_OUTPUT, cert_output)

    def test_product_cert_output(self):
        command = CatCertCommandStub(certdata.PRODUCT_CERT_V1_0)
        command.main(['will_use_stub'])

        cert_output = self.mock_stdout.buffer
        self.assert_string_equals(certdata.PRODUCT_CERT_V1_0_OUTPUT, cert_output)

    def test_identity_cert_output(self):
        command = CatCertCommandStub(certdata.IDENTITY_CERT)
        command.main(['will_use_stub'])

        cert_output = self.mock_stdout.buffer
        self.assert_string_equals(certdata.IDENTITY_CERT_OUTPUT, cert_output)
