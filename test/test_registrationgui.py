import unittest
import time
import gtk
import gobject
import logging

import mock
import rhsm_display
rhsm_display.set_display()

from stubs import StubBackend, StubFacts, StubUEP, StubProduct, \
    StubProductCertificate, StubProductDirectory
from subscription_manager.gui.registergui import RegisterScreen, \
        CredentialsScreen, MissingCaCertException, ServerUrlParseError
from subscription_manager.gui.registergui import DONT_CHANGE, PROGRESS_PAGE, CHOOSE_SERVER_PAGE, CREDENTIALS_PAGE, \
        OWNER_SELECT_PAGE, ENVIRONMENT_SELECT_PAGE, PERFORM_REGISTER_PAGE, SELECT_SLA_PAGE, CONFIRM_SUBS_PAGE, \
        PERFORM_SUBSCRIBE_PAGE, FINISH
from subscription_manager import logutil
gtk.gdk.threads_init()


class ColorFormatter(logging.Formatter):
    FORMAT = ("[$BOLD%(name)-20s$RESET][%(levelname)-18s]  "
              "%(message)s "
              "($BOLD%(filename)s$RESET:%(lineno)d)")

    FORMAT = (u"""$BOLD[%(levelname)s]$RESET [tname:\033[32m%(threadName)s]$RESET @%(filename)s:%(lineno)d - $BOLD%(message)s$RESET""")
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[1;%dm"
    BOLD_SEQ = "\033[1m"

    COLORS = {
        'WARNING': YELLOW,
        'INFO': YELLOW,
        'DEBUG': BLUE,
        'CRITICAL': YELLOW,
        'ERROR': RED
    }

    def formatter_msg(self, msg, use_color=True):
        if use_color:
            msg = msg.replace("$RESET", self.RESET_SEQ).replace("$BOLD", self.BOLD_SEQ)
        else:
            msg = msg.replace("$RESET", "").replace("$BOLD", "")
        return msg

    def __init__(self, use_color=True):
        msg = self.formatter_msg(self.FORMAT, use_color)
        logging.Formatter.__init__(self, msg)
        self.use_color = use_color

    def format(self, record):
        levelname = record.levelname
        if self.use_color and levelname in self.COLORS:
            fore_color = 30 + self.COLORS[levelname]
            levelname_color = self.COLOR_SEQ % fore_color + levelname + self.RESET_SEQ
            record.levelname = levelname_color
        return logging.Formatter.format(self, record)


def _get_handler():
    #%(asctime)s tid:%(thread)d
    #fmt = u'\033[33m**: tname:%(threadName)s @%(filename)s:%(lineno)d - %(message)s\033[0m'
    fmt = u': tname:%(threadName)s @%(filename)s:%(lineno)d - %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(use_color=True))
    #handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(logging.DEBUG)

    return handler

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_get_handler())


class RegisterScreenStubUEP(StubUEP):
    enviromnments = True

    def supports_resource(self, resource):
        if resource == 'environments':
            return self.enviromnments
        return True

    def getEnvironmentList(self, ownerkey):
        return [{'name':'Production', 'id':'1'}]

    def getConsumer(self, consumer_uuid):
        return  {'uuid': 'MOCKUUID',
                 'owner': {'key': 'dummyowner'},
                 'serviceLevel': 'Professional'}

    def dryRunBind(self, consumer_uuid, sla):
        if sla == 'Super Pro':
            return [{'pool': {'productName':'someProduct',
                          'productId': 'someProduct',
                          'providedProducts': [{'productId':'someproduct',
                                                'productName': 'Some Product'}],
                          'id':'23423'},
                'quantity': '5'}]

        return [{'pool': {'productName':'someProduct',
                          'productId': 'someProduct',
                          'providedProducts':[],
                          'id':'23423'},
                'quantity': '5'}]

    def bindByEntitlementPool(self, consumer_uuid, pool_id, quantity):
        return []


class RegisterScreenTests(unittest.TestCase):
    def setUp(self):
        # setup some stubs since we already have them
        uep = RegisterScreenStubUEP()
        mock_uuid = 'MOCKUUID'
        uep.setConsumer(mock_uuid)
        self.backend = StubBackend(uep=RegisterScreenStubUEP())
        self.backend.entitlement_dir = mock.Mock()
        self.backend.entitlement_dir.list.return_value = []

        # some stub products to try to subscribe to
        self.stub_product = StubProduct('someproduct')
        self.stub_product_certs = [StubProductCertificate(self.stub_product)]
        stub_product_dir = StubProductDirectory(self.stub_product_certs)

        # keep track of these so teardown is easer
        self.patchers = []
        # setup mocks for all the interesting bits
        # why a instance variable? becomes we may need to stop these patches for
        # some tests
        self.pm_patcher = mock.patch('subscription_manager.gui.registergui.ProfileManager')
        self.mock_profile_manager = self.pm_patcher.start()
        # profile manager, so we don't read packages installed on tests system
        mpm = self.mock_profile_manager.return_value
        self.patchers.append(self.pm_patcher)

        self.ipm_patcher = mock.patch('subscription_manager.gui.registergui.InstalledProductsManager')
        mock_installed_pm = self.ipm_patcher.start()
        # mock InstalledProductsManager so we dont load products list
        m_ipm = mock_installed_pm.return_value
        m_ipm.format_for_server.return_value = [{'productId': 'product_id',
                                                 'productName': 'product_name'}]
        self.patchers.append(self.ipm_patcher)

        self.cs_patcher = mock.patch('subscription_manager.gui.registergui.CertSorter')
        mock_cert_sorter = self.cs_patcher.start()
        # mock cert sorter
        mcs_in = mock_cert_sorter.return_value
        mcs_in.installed_products = {'someproduct': self.stub_product_certs[0]}
        mcs_in.unentitled_products = {'someproduct': self.stub_product_certs[0]}
        self.patchers.append(self.cs_patcher)

        self.fc_patcher = mock.patch('subscription_manager.gui.registergui.managerlib.fetch_certificates')
        self.mock_fetch = self.fc_patcher.start()
        logging.debug("self.mock_fetch: %s" % self.mock_fetch)
        self.mock_fetch.return_value = []
        self.patchers.append(self.fc_patcher)

        self.fc2_patcher = mock.patch('subscription_manager.managerlib.fetch_certificates')
        self.mock_fetch2 = self.fc2_patcher.start()
        logging.debug("self.mock_fetch2: %s" % self.mock_fetch2)
        self.mock_fetch2.return_value = []
        self.patchers.append(self.fc2_patcher)

        self.pcc_patcher = mock.patch('subscription_manager.gui.registergui.managerlib.persist_consumer_cert')
        mock_persist = self.pcc_patcher.start()
        mock_persist.return_value = True
        self.patchers.append(self.pcc_patcher)

        self.ivsi_patcher = mock.patch('subscription_manager.gui.registergui.is_valid_server_info')
        self.mock_is_valid = self.ivsi_patcher.start()
        self.mock_is_valid.return_value = True
        self.patchers.append(self.ivsi_patcher)

        self.va_patcher = mock.patch('subscription_manager.gui.registergui.CredentialsScreen._validate_account')
        self.mock_validate_account = self.va_patcher.start()
        self.mock_validate_account.return_calue = True
        self.patchers.append(self.va_patcher)

        self.cm_patcher = mock.patch('subscription_manager.gui.registergui.CertManager')
        cert_manager_mock = self.cm_patcher.start()
        self.patchers.append(self.cm_patcher)

        self.backend.product_dir = mock.Mock()
        self.backend.product_dir.list.return_value = []
        self.consumer = mock.Mock()
        self.consumer.getConsumerId.return_value = mock_uuid
        expected_facts = {'fact1': 'one',
                          'fact2': 'two',
                          'system': '',
                          'system.uuid': mock_uuid}
        self.facts = StubFacts(fact_dict=expected_facts)

        self.finished = False
        self.rs = RegisterScreen(self.backend, self.consumer, self.facts, callbacks=[self._finish_callback])

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    def _finish_callback(self):
        print "FINISH CALLBACK"
        self.finished = True

    # make sure we are on the screen we think we should be
    # and then go to the next one
    def _validate_screen(self, screen_enum):
        print "validate_screen: ", screen_enum, self.rs._current_screen
        self.assertEquals(screen_enum, self.rs._current_screen)
        # these are "terminal" screens
        if screen_enum < PERFORM_SUBSCRIBE_PAGE:
            self.rs._on_register_button_clicked(None)

    def _validate_finish(self):
        self.assertTrue(self.finished)

    def test_show(self):
        self.rs.show()

    def test_register(self):

        self.rs.show()

        # kick off the async flow
        self.rs.register()

        # simulate hitting the ok button
        # we could do this as a while loop, but it's bit
        # hard to tell when get to the end atm
        # and this is a bit more explicit
        # FIXME: we should verify we are on the screen we think we should be

        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)

        self._validate_screen(PERFORM_SUBSCRIBE_PAGE)


#    def test_register_exception_fetch_certificates(self):
#        self.mock_fetch.side_effect = IOError('fetch certificate io error')
#        self.rs.show()
#        self.rs.register()
#        self._validate_screen(CREDENTIALS_PAGE)
#        self._validate_screen(OWNER_SELECT_PAGE)
#
#        self.assertRaises(IOError, self._validate_screen, PERFORM_SUBSCRIBE_PAGE)

    def test_register_invalid_server_name(self):
        self.mock_is_valid.return_value = False
        self.rs.show()
        result = self.rs.register()
        self._validate_screen(CHOOSE_SERVER_PAGE)
        self.assertFalse(result)

    def test_register_missing_ca_cert(self):
        self.mock_is_valid.side_effect = MissingCaCertException()
        self.rs.show()
        result = self.rs.register()
        self._validate_screen(CHOOSE_SERVER_PAGE)
        self.assertFalse(result)

    @mock.patch('subscription_manager.gui.registergui.errorWindow')
    @mock.patch('subscription_manager.gui.registergui.CredentialsScreen._initialize_consumer_name')
    def test_register_invalid_consumername(self, mock_init_consumer_name, mock_error_window):
        # just skip setting the consumer name to hostname and see what happens
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        # we created an error window
        self.assertTrue(mock_error_window.called)

    @mock.patch('subscription_manager.gui.registergui.errorWindow')
    @mock.patch('subscription_manager.gui.registergui.parse_server_info')
    def test_register_server_url_parse_error(self, mock_parse_server, mock_error_window):
        mock_parse_server.side_effect = ServerUrlParseError('ehtttpe::/this_is.a.bogus/url://:', "very bogus url")
        self.rs.show()
        self.rs.register()
        self._validate_screen(CHOOSE_SERVER_PAGE)
        self.assertTrue(mock_error_window.called)

    @mock.patch.object(RegisterScreenStubUEP, 'supports_resource')
    def test_register_no_env_support(self, mock_supports_resource):
        mock_supports_resource.return_value = False
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        # config screen is weird, fix
        self.rs._on_register_button_clicked(None)
        self.assertEquals('Professional', self.rs.dry_run_result.service_level)
        self.assertEquals('23423', self.rs.dry_run_result.get_pool_quantities()[0][0])

    # FIXME: this is known broken at the moment, we don't handle
    # exceptions
    @mock.patch.object(RegisterScreenStubUEP, 'supports_resource')
    def test_register_env_throws_exception(self, mock_supports_resource):
        mock_supports_resource.side_effect = IOError("some message about supports_resource('environments') failing")
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self.rs._on_register_button_clicked(None)
#        self._validate_screen(OWNER_SELECT_PAGE)
        self._validate_finish()
        # we don't seem to handle this exception well, we get the dialog,
        # but we don't stop the registration process... so 
        # EnvSelect.apply fails because no data is available
#        self.rs._on_register_button_clicked(None)

    @mock.patch.object(RegisterScreenStubUEP, 'getEnvironmentList')
    def test_register_multiple_envs_available(self, mock_get_envs):
        mock_get_envs.return_value = [{'name':'Production', 'id':'1'},
                                      {'name':'Test', 'id': '2'},
                                      {'name':'Stage', 'id': '3'}]
        self.rs.show()
        res = self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self._validate_screen(PERFORM_REGISTER_PAGE)
        self._validate_screen(PERFORM_SUBSCRIBE_PAGE)
        self.rs.register()

    @mock.patch('subscription_manager.gui.utils.errorWindow')
    @mock.patch.object(RegisterScreenStubUEP, 'getOwnerList')
    def test_register_exception_on_ownerlist(self, mock_ownerlist, mock_error_window):
        mock_ownerlist.side_effect = Exception('some msg')
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self.assertTrue(mock_error_window.called)

    # FIXME: not sure what is going on, we set this up in the setUp, why did it "unmock"
    @mock.patch('subscription_manager.gui.registergui.managerlib.fetch_certificates')
    @mock.patch.object(RegisterScreenStubUEP, 'getOwnerList')
    def test_register_multiple_owners(self, mock_ownerlist, mock_fetch_certs):
        mock_ownerlist.return_value = [{'key': 'dummyowner',
                                        'displayName': 'Dummy Owner'},
                                       {'key': 'someotherguy',
                                        'displayName': 'Some Other Owner'},
                                       {'key': 'preowner',
                                        'displayName': 'Larry'}]
        mock_fetch_certs.return_value = []
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self._validate_screen(ENVIRONMENT_SELECT_PAGE)
        self._validate_screen(PERFORM_SUBSCRIBE_PAGE)
        #self._validate_finish()
        #self._validate_screen(CONFIRM_SUBS_PAGE)
        self.rs._on_register_button_clicked(None)
        #self._validate_finish()

    @mock.patch('subscription_manager.gui.utils.errorWindow')
    @mock.patch.object(RegisterScreenStubUEP, 'getOwnerList')
    def test_register_no_owners(self, mock_ownerlist, mock_error_window):
        mock_ownerlist.return_value = []
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)

        self._validate_screen(OWNER_SELECT_PAGE)
        self.assertTrue(mock_error_window.called)
        self._validate_finish()

    @mock.patch('subscription_manager.gui.utils.errorWindow')
    @mock.patch.object(RegisterScreenStubUEP, 'registerConsumer')
    def test_register_exception_on_register(self, mock_register_consumer, mock_error_window):
        mock_register_consumer.side_effect = Exception('some exception')
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self.assertTrue(mock_error_window.called)

    @mock.patch('subscription_manager.managerlib.fetch_certificates')
    @mock.patch('subscription_manager.gui.utils.errorWindow')
    @mock.patch.object(RegisterScreenStubUEP, 'bindByEntitlementPool')
    def test_register_exception_on_subscribe(self, mock_subscribe, mock_error_window, mock_fetch):
        mock_fetch.return_value = []
        mock_subscribe.side_effect = Exception('some exception')
        self.rs.show()
        self.rs.register()
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self._validate_screen(PERFORM_SUBSCRIBE_PAGE)
        # we have to actually do something post the subscribe.pre
        # if we want to catch the exception from the thread
        self.rs._on_register_button_clicked(None)
        self._validate_finish()
        self.assertTrue(mock_error_window.called)

    # yes, we are mocking a stub...
    @mock.patch('subscription_manager.gui.registergui.OkDialog')
    @mock.patch.object(RegisterScreenStubUEP, 'getConsumer')
    def test_register_no_slas(self, mock_get_consumer, mock_error_window):
        mock_get_consumer.return_value = {'uuid': 'MOCKUUID',
                                          'owner': {'key': 'dummyowner'}}
        self.rs.show()

        self.rs.register()
        #self._validate_finish()
        #self.assertTrue(mock_error_window.called)
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        #self._validate_screen(SELECT_SLA_PAGE)
        self.assertTrue(mock_error_window.called)
#        gtk.main_iteration()
        #time.sleep(10)
        #self.rs._on_register_button_clicked(None)
        #self.rs._on_register_button_clicked(None)
        #self.rs._on_register_button_clicked(None)

    @mock.patch.object(RegisterScreenStubUEP, 'getConsumer')
    def test_register_multiple_slas_one_match(self, mock_get_consumer):
        mock_get_consumer.return_value = {'uuid': 'MOCKUUID',
                                          'owner': {'key': 'dummyowner'},
                                          'serviceLevel': ''}
        self.rs.show()
        self.rs.register()

        # click through CHOOSE_SERVER_PAGE/ChooseServerScreen
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self.rs._on_register_button_clicked(None)
        self.assertEquals(self.rs.dry_run_result.service_level, "Super Pro")

    @mock.patch.object(RegisterScreenStubUEP, 'getConsumer')
    @mock.patch.object(RegisterScreenStubUEP, 'dryRunBind')
    def test_register_multiple_slas_multiple_matches(self, mock_dry_run_bind,
                                                     mock_get_consumer):
        mock_get_consumer.return_value = {'uuid': 'MOCKUUID',
                                          'owner': {'key': 'dummyowner'},
                                          'serviceLevel': ''}
        mock_dry_run_bind.return_value = [{'pool': {'productName':'someProduct',
                                                    'productId': '23423',
                                                    'providedProducts': [{'productId':'someproduct',
                                                                          'productName': 'Some Product'}],
                                                    'id':'23423'},
                                           'quantity': {}},
                                          {'pool': {'productName':'someOtherProduct',
                                                    'productId': '23424',
                                                    'providedProducts': [{'productId':'someOtherProduct',
                                                                          'productName': 'Some Product'}],
                                                    'id':'23424'},
                                           'quantity': {}}
                                          ]
        self.rs.show()
        self.rs.register()

        #FIXME: we should verify we are at the right screens
        # and the right attributes for RegisterScreen are set
        self._validate_screen(CREDENTIALS_PAGE)
        self._validate_screen(OWNER_SELECT_PAGE)
        self._validate_screen(CONFIRM_SUBS_PAGE)

        # confirum service level screen is weird...
        self.rs._on_register_button_clicked(None)
        self.assertEquals(self.rs.dry_run_result.service_level, "Pro")


class CredentialsScreenTests(unittest.TestCase):

    def setUp(self):
        self.backend = StubBackend()
        self.parent = mock.Mock(spec='subscription_manager.gui.registergui.RegisterScreen')
        self.parent.window = None

        self.screen = CredentialsScreen(self.parent, self.backend)

    def test_clear_credentials_dialog(self):
        # Pull initial value here since it will be different per machine.
        default_consumer_name_value = self.screen.consumer_name.get_text()
        self.screen.account_login.set_text("foo")
        self.screen.account_password.set_text("bar")
        self.screen.skip_auto_bind.set_active(True)
        self.screen.consumer_name.set_text("CONSUMER")
        self.screen.clear()
        self.assertEquals("", self.screen.account_login.get_text())
        self.assertEquals("", self.screen.account_password.get_text())
        self.assertFalse(self.screen.skip_auto_bind.get_active())
        self.assertEquals(default_consumer_name_value,
                          self.screen.consumer_name.get_text())

    def test_validate_account(self):
        default_consumer_name_value = self.screen.consumer_name.get_text()
        self.screen.account_login.set_text("foo")
        self.screen.account_password.set_text("bar")
        self.screen.skip_auto_bind.set_active(True)
        self.screen.consumer_name.set_text("CONSUMER")

        ret = self.screen.apply()
        self.assertEquals(ret, OWNER_SELECT_PAGE)

    def test_validate_account_no_consumername(self):
        default_consumer_name_value = self.screen.consumer_name.get_text()
        self.screen.account_login.set_text("foo")
        self.screen.account_password.set_text("bar")
        self.screen.skip_auto_bind.set_active(True)

        self.screen.consumer_name.set_text("")
        ret = self.screen.apply()
        self.assertEquals(ret, DONT_CHANGE)

    def test_validate_account_no_username(self):
        self.screen.account_login.set_text("")
        ret = self.screen.apply()
        self.assertEquals(ret, DONT_CHANGE)

    def test_validate_account_no_password(self):
        self.screen.account_login.set_text("foo")
        self.screen.account_password.set_text("")
        ret = self.screen.apply()
        self.assertEquals(ret, DONT_CHANGE)
