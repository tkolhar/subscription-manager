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

import StringIO
from rhsm import config
import random
import tempfile

from subscription_manager.cert_sorter import CertSorter
from subscription_manager.cache import StatusCache, ProductStatusCache
from rhsm.certificate import GMT

# config file is root only, so just fill in a stringbuffer
cfg_buf = """
[foo]
bar =
[server]
hostname = server.example.conf
prefix = /candlepin
port = 8443
insecure = 1
ssl_verify_depth = 3
ca_cert_dir = /etc/rhsm/ca/
proxy_hostname =
proxy_port =
proxy_user =
proxy_password =

[rhsm]
baseurl= https://content.example.com
repo_ca_cert = %(ca_cert_dir)sredhat-uep.pem
productCertDir = /etc/pki/product
entitlementCertDir = /etc/pki/entitlement
consumerCertDir = /etc/pki/consumer

[rhsmcertd]
certCheckInterval = 240
"""

test_config = StringIO.StringIO(cfg_buf)


class StubConfig(config.RhsmConfigParser):
    def __init__(self, config_file=None, defaults=None):
        defaults = defaults or config.DEFAULTS
        config.RhsmConfigParser.__init__(self, config_file=config_file, defaults=defaults)
        self.raise_io = None
        self.fileName = config_file
        self.store = {}

    # isntead of reading a file, let's use the stringio
    def read(self, filename):
        self.readfp(test_config, "foo.conf")

    def set(self, section, key, value):
#        print self.sections()
        self.store['%s.%s' % (section, key)] = value

    def save(self, config_file=None):
        if self.raise_io:
            raise IOError
        return None

    # replace read with readfp on stringio


def stubInitConfig():
    return StubConfig()

# create a global CFG object,then replace it with out own that candlepin
# read from a stringio
config.initConfig(config_file="test/rhsm.conf")
config.CFG = StubConfig()

# we are not actually reading test/rhsm.conf, it's just a placeholder
config.CFG.read("test/rhsm.conf")

from datetime import datetime, timedelta

from subscription_manager.certdirectory import EntitlementDirectory, ProductDirectory
from subscription_manager.certlib import ActionLock
from rhsm.certificate import parse_tags, Content
from rhsm.certificate2 import EntitlementCertificate, ProductCertificate, \
        Product, Content, Order


class MockActionLock(ActionLock):
    PATH = tempfile.mkstemp()[1]


class MockStdout:
    def __init__(self):
        self.buffer = ""

    def write(self, buf):
        self.buffer = self.buffer + buf

    @staticmethod
    def isatty(buf=None):
        return False


MockStderr = MockStdout


class StubProduct(Product):

    def __init__(self, product_id, name=None, version=None, architectures=None,
            provided_tags=None):

        # Initialize some defaults:
        if not name:
            name = product_id

        if not architectures:
            architectures = ["x86_64"]

        if not version:
            version = "1.0"

        # Tests sadly pass these in as a flat string. # TODO
        if provided_tags:
            provided_tags = parse_tags(provided_tags)

        super(StubProduct, self).__init__(id=product_id, name=name, version=version,
                                          architectures=architectures,
                                          provided_tags=provided_tags)


class StubContent(Content):

    def __init__(self, label, name=None, vendor="",
            url="", gpg="", enabled=1, metadata_expire=None, required_tags="",
            content_type="yum"):
        name = label
        if name:
            name = name
        if required_tags:
            required_tags = parse_tags(required_tags)
        super(StubContent, self).__init__(content_type=content_type, name=name, label=label,
                                          vendor=vendor, url=url, gpg=gpg, enabled=enabled,
                                          metadata_expire=metadata_expire,
                                          required_tags=required_tags)


class StubProductCertificate(ProductCertificate):

    def __init__(self, product, provided_products=None, start_date=None,
            end_date=None, provided_tags=None):

        products = [product]
        if provided_products:
            products = products + provided_products

        self.name = product.name
        version = product.version

        # TODO: product should be a StubProduct, check for strings coming in and error out
        self.product = product
        self.provided_products = []
        if provided_products:
            self.provided_products = provided_products

        self.provided_tags = set()
        if provided_tags:
            self.provided_tags = set(provided_tags)

        if not start_date:
            start_date = datetime.now() - timedelta(days=100)
        if not end_date:
            end_date = datetime.now() + timedelta(days=365)

        super(StubProductCertificate, self).__init__(products=products,
                                                     serial=random.randint(1, 10000000),
                                                     start=start_date, end=end_date,
                                                     version=version)

    def __str__(self):
        s = []
        s.append('StubProductCertificate:')
        s.append('===================================')
        for p in self.products:
            s.append(str(p))
        return '\n'.join(s)


class StubEntitlementCertificate(EntitlementCertificate):

    def __init__(self, product, provided_products=None, start_date=None, end_date=None,
            content=None, quantity=1, stacking_id=None, sockets=2, service_level=None,
            ram=None, pool=None, ent_id=None):

        # If we're given strings, create stub products for them:
        if isinstance(product, str):
            product = StubProduct(product)
        if provided_products:
            temp = []
            for p in provided_products:
                temp.append(StubProduct(p))
            provided_products = temp

        products = []
        if product:
            products.append(product)
        if provided_products:
            products = products + provided_products

        if not start_date:
            start_date = datetime.now()
        if not end_date:
            end_date = start_date + timedelta(days=365)

        # to simulate a cert with no product
        sku = None
        name = None
        if product:
            sku = product.id
            name = product.name
        order = Order(name=name, number="592837", sku=sku,
                    stacking_id=stacking_id, socket_limit=sockets,
                    service_level=service_level, quantity_used=quantity,
                    ram_limit=ram)
        order.warning_period = 42

        if content is None:
            content = []

        path = "/tmp/fake_ent_cert.pem"
        self.is_deleted = False

        # might as well make this a big num since live serials #'s are already > maxint
        self.serial = random.randint(1000000000000000000, 10000000000000000000000)
        # write these to tmp, could we abuse PATH thing in certs for tests?

        path = "/tmp/fake_ent_cert-%s.pem" % self.serial
        super(StubEntitlementCertificate, self).__init__(path=path, products=products, order=order,
                                                         content=content, pool=pool, start=start_date,
                                                         end=end_date, serial=self.serial)
        if ent_id:
            self.subject = {'CN': ent_id}

    def delete(self):
        self.is_deleted = True

    def is_expiring(self, on_date=None):
        gmt = datetime.utcnow()
        if on_date:
            gmt = on_date
        gmt = gmt.replace(tzinfo=GMT())
        warning_time = timedelta(days=int(self.order.warning_period))
        return self.valid_range.end() - warning_time < gmt


class StubCertificateDirectory(EntitlementDirectory):
    """
    Stub for mimicing behavior of an on-disk certificate directory.
    Can be used for both entitlement and product directories as needed.
    """

    path = "this/is/a/stub/cert/dir"
    expired = False

    def __init__(self, certificates=None):
        self.certs = certificates
        if certificates is None:
            self.certs = []
        self.list_called = False

    def list(self):
        self.list_called = True
        return self.certs

    def _check_key(self, cert):
        """
        Fake filesystem access here so we don't try to read real keys.
        """
        return True

    def getCerts(self):
        return self.certs

# so we can use a less confusing name when we use this stub
StubEntitlementDirectory = StubCertificateDirectory


class StubProductDirectory(StubCertificateDirectory, ProductDirectory):
    """
    Stub for mimicing behavior of an on-disk certificate directory.
    Can be used for both entitlement and product directories as needed.
    """

    path = "this/is/a/stub"

    def __init__(self, certificates=None, pids=None):
        """
        Pass list of product ID strings instead of certificates to have
        stub product certs created for you.
        """
        if pids is not None:
            certificates = []
            for pid in pids:
                certificates.append(StubProductCertificate(StubProduct(pid)))
        super(StubProductDirectory, self).__init__(certificates)


class StubConsumerIdentity(object):
    CONSUMER_NAME = "John Q Consumer"
    CONSUMER_ID = "211211381984"
    SERIAL = "23234523452345234523453453434534534"

    def __init__(self, keystring, certstring):
        self.key = keystring
        self.cert = certstring

    @classmethod
    def existsAndValid(cls):
        return True

    @classmethod
    def exists(cls):
        return False

    def getConsumerName(self):
        return StubConsumerIdentity.CONSUMER_NAME

    def getConsumerId(self):
        return StubConsumerIdentity.CONSUMER_ID

    def getSerialNumber(self):
        return StubConsumerIdentity.SERIAL

    @classmethod
    def read(cls):
        return StubConsumerIdentity("", "")

    @classmethod
    def certpath(cls):
        return ""

    @classmethod
    def keypath(cls):
        return ""


class StubUEP:
    def __init__(self, host=None, ssl_port=None, handler=None,
                 username=None, password=None,
                 proxy_hostname=None, proxy_port=None,
                 proxy_user=None, proxy_password=None,
                 cert_file=None, key_file=None):
        self.registered_consumer_info = {"uuid": 'dummy-consumer-uuid'}
        self.environment_list = []
        self.called_unregister_uuid = None
        self.called_unbind_uuid = None
        self.called_unbind_serial = []

    def supports_resource(self, resource):
        return False

    def registerConsumer(self, name, type, facts, owner, environment, keys,
                         installed_products):
        return self.registered_consumer_info

    def unregisterConsumer(self, uuid):
        self.called_unregister_uuid = uuid

    def getOwnerList(self, username):
        return [{'key': 'dummyowner'}]

    def getOwner(self):
        return {'key': 'dummyowner'}

    def updatePackageProfile(self, uuid, pkg_dicts):
        pass

    def getProduct(self):
        return {}

    def getRelease(self, consumerId):
        return {'releaseVer': ''}

    def getServiceLevelList(self, owner):
        return ['Pro', 'Super Pro', 'ProSumer']

    def updateConsumer(self, consumer, installed_products=None, service_level=None, release=None, autoheal=None):
        return consumer

    def setEnvironmentList(self, env_list):
        self.environment_list = env_list

    def getEnvironmentList(self, owner):
        return self.environment_list

    def setConsumer(self, consumer):
        self.consumer = consumer

    def getConsumer(self, consumerId):
        return self.consumer

    def unbindAll(self, consumer):
        self.called_unbind_uuid = consumer

    def unbindBySerial(self, consumer, serial):
        self.called_unbind_serial.append(serial)

    def getCertificateSerials(self, consumer):
        return []

    def getCompliance(self, uuid):
        return {}


class StubBackend:
    def __init__(self, uep=StubUEP()):
        self.cp_provider = StubCPProvider()
        self.entitlement_dir = None
        self.product_dir = None
        self.content_connection = None
        self.cs = StubCertSorter()

    def monitor_certs(self, callback):
        pass

    def monitor_identity(self, callback):
        pass

    def create_admin_uep(self, username, password):
        return StubUEP(username, password)

    def update(self):
        pass


class StubContentConnection:
    def __init__(self):
        pass


class StubFacts(object):
    def __init__(self, fact_dict=None, facts_changed=True):
        fact_dict = fact_dict or {}
        self.facts = fact_dict

        self.delta_values = {}
        # Simulate the delta as being the new set of facts provided.
        if facts_changed:
            self.delta_values = self.facts

    def get_facts(self, refresh=True):
        return self.facts

    def has_changed(self):
        return self.delta_values

    def update_check(self, uep, consumer_uuid, force=False):
        uep.updateConsumerFacts(consumer_uuid, self.facts)

    def get_last_update(self):
        return None


class StubConsumer:
    def __init__(self):
        self.uuid = None

    def is_valid(self):
        return True

    def reload(self):
        pass

    def getConsumerId(self):
        return "12341234234"


class StubCertLib:
    def __init__(self, uep=StubUEP()):
        self.uep = uep

    def update(self):
        pass


class StubCertSorter(CertSorter):

    def __init__(self):
        super(StubCertSorter, self).__init__()

    def update_product_manager(self):
        pass

    def _parse_server_status(self):
        # Override this method to just leave all fields uninitialized so
        # tests can do whatever they wish with them.
        pass


class StubCPProvider(object):

    consumer_auth_cp = StubUEP()
    basic_auth_cp = StubUEP()
    no_auth_cp = StubUEP()

    def set_connection_info(self,
                host=None,
                ssl_port=None,
                handler=None,
                cert_file=None,
                key_file=None,
                proxy_hostname_arg=None,
                proxy_port_arg=None,
                proxy_user_arg=None,
                proxy_password_arg=None):
        self.consumer_auth_cp = StubUEP()
        self.basic_auth_cp = StubUEP()
        self.no_auth_cp = StubUEP()

    def set_user_pass(self, username=None, password=None):
        pass

    def clean(self):
        pass

    def get_consumer_auth_cp(self):
        return self.consumer_auth_cp

    def get_basic_auth_cp(self):
        return self.basic_auth_cp

    def get_no_auth_cp(self):
        return self.no_auth_cp


class StubStatusCache(StatusCache):

    def write_cache(self):
        pass

    def delete_cache(self):
        self.server_status = None


class StubProductStatusCache(ProductStatusCache):

    def write_cache(self):
        pass

    def delete_cache(self):
        self.server_status = None
