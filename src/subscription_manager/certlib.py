#
# Copyright (c) 2010 Red Hat, Inc.
#
# Authors: Jeff Ortel <jortel@redhat.com>
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

from datetime import datetime, timedelta
import gettext
import logging
import socket
import syslog

from rhsm.config import initConfig
from rhsm.certificate import Key, create_from_pem, GMT

from subscription_manager.certdirectory import Writer
from subscription_manager.identity import ConsumerIdentity
from subscription_manager.injection import CERT_SORTER, PLUGIN_MANAGER, IDENTITY, ACTION_LOCK, require
import subscription_manager.injection as inj

log = logging.getLogger('rhsm-app.' + __name__)

_ = gettext.gettext

cfg = initConfig()


def system_log(message, priority=syslog.LOG_NOTICE):
    syslog.openlog("subscription-manager")
    syslog.syslog(priority, message.encode("utf-8"))


# This guys seems unneccasary
#class Action:

#    def __init__(self, uep=None, entdir=None):
#        self.entdir = entdir or inj.require(inj.ENT_DIR)
#        self.uep = uep


# TODO: *Lib objects should probably all support a Report object
#        ala CertLib, even if most of them would be simple or
#        or noops. Would make logging easier and more useful
#        and reduce some of the random variations in *Lib
class Locker(object):

    def __init__(self):
        self.lock = self._get_lock()

    def run(self, action):
        self.lock.acquire()
        try:
            return action()
        finally:
            self.lock.release()

    def _get_lock(self):
        return inj.require(ACTION_LOCK)


class DataLib(object):
    def __init__(self, uep=None):
        self.locker = Locker()
        self.uep = uep
        self.report = None

    def update(self):
        self.report = self.locker.run(self._do_update)
        return self.report

    def _do_update(self):
        """Thing the "lib" needs to do"""
        return


class EntCertLib(DataLib):
    def _do_update(self):
        action = EntCertUpdateAction(uep=self.uep)
        return action.perform()


# this guy is an oddball
class EntCertDeleteLib(object):
    def __init__(self, serial_numbers=None,
                entdir=None):
        self.locker = Locker()
        self.entdir = entdir

    def delete(self):
        self.locker.run(self._do_delete)

    def _do_delete(self):
        action = EntCertDeleteAction(entdir=self.entdir,
                                    serial_numbers=self.serial_numbers)
        return action.perform()


class IdentityCertLib(DataLib):
    """
    An object to update the identity certificate in the event the server
    deems it is about to expire. This is done to prevent the identity
    certificate from expiring thus disallowing connection to the server
    for updates.
    """

    def _do_update(self):
        report = ActionReport()
        if not ConsumerIdentity.existsAndValid():
            # we could in theory try to update the id in the
            # case of it being bogus/corrupted, ala #844069,
            # but that seems unneeded
            # FIXME: more details
            report._status = 0
            return report

        from subscription_manager import managerlib

        idcert = ConsumerIdentity.read()
        uuid = idcert.getConsumerId()
        consumer = self.uep.getConsumer(uuid)
        # only write the cert if the serial has changed
        if idcert.getSerialNumber() != consumer['idCert']['serial']['serial']:
            log.debug('identity certificate changed, writing new one')
            managerlib.persist_consumer_cert(consumer)
        report._status = 1
        return report


# TODO: rename to EntitlementCertDeleteAction
class EntCertDeleteAction(object):
    def __init__(self, entdir=None):
        self.entdir = entdir

    def perform(self, serial_numbers):
        for sn in serial_numbers:
            cert = self.entdir.find(sn)
            if cert is None:
                continue
            cert.delete()
        return self


# TODO: rename to EntitlementCertUpdateAction
class EntCertUpdateAction(object):

    def __init__(self, uep=None, entdir=None, report=None):
        self.uep = uep
        self.entdir = entdir or inj.require(inj.ENT_DIR)
        self.identity = require(IDENTITY)
        self.report = EntCertUpdateReport()

    # NOTE: this is slightly at odds with the manual cert import
    #       path, manual import certs wont get a 'report', etc
    def perform(self):
        local = self._get_local_serials()
        try:
            expected = self._get_expected_serials()
        except socket.error, ex:
            log.exception(ex)
            log.error('Cannot modify subscriptions while disconnected')
            raise Disconnected()

        missing_serials = self._find_missing_serials(local, expected)
        rogue_serials = self._find_rogue_serials(local, expected)

        self.delete(rogue_serials)
        self.install(missing_serials)

        log.info('certs updated:\n%s', self.report)
        self.syslog_results()

        # if we want the full report, we can get it, but
        # this makes CertLib.update() have same sig as reset
        # of *Lib.update
        return self.report

    def install(self, missing_serials):

        cert_bundles = self.get_certificates_by_serial_list(missing_serials)

        ent_cert_bundles_installer = EntitlementCertBundlesInstaller(self.report)
        ent_cert_bundles_installer.install(cert_bundles)

    def _find_missing_serials(self, local, expected):
        """ Find serials from the server we do not have locally. """
        missing = [sn for sn in expected if sn not in local]
        return missing

    def _find_rogue_serials(self, local, expected):
        """ Find serials we have locally but are not on the server. """
        rogue = [local[sn] for sn in local if not sn in expected]
        return rogue

    def syslog_results(self):
        for cert in self.report.added:
            system_log("Added subscription for '%s' contract '%s'" %
                       (cert.order.name, cert.order.contract))
            for product in cert.products:
                system_log("Added subscription for product '%s'" %
                           (product.name))
        for cert in self.report.rogue:
            system_log("Removed subscription for '%s' contract '%s'" %
                       (cert.order.name, cert.order.contract))
            for product in cert.products:
                system_log("Removed subscription for product '%s'" %
                           (product.name))

    def _get_local_serials(self):
        local = {}
        #certificates in grace period were being renamed everytime.
        #this makes sure we don't try to re-write certificates in
        #grace period
        # XXX since we don't use grace period, this might not be needed
        self.entdir.refresh()
        for valid in self.entdir.list():
            sn = valid.serial
            self.report.valid.append(sn)
            local[sn] = valid
        return local

    def _get_consumer_id(self):
        try:
            cid = ConsumerIdentity.read()
            return cid.getConsumerId()
        except Exception, e:
            log.error(e)
            raise Disconnected()

    def get_certificate_serials_list(self):
        results = []
        # if there is no UEP object, short circuit
        if self.uep is None:
            return results
        reply = self.uep.getCertificateSerials(self._get_consumer_id())
        for d in reply:
            sn = d['serial']
            results.append(sn)
        return results

    def get_certificates_by_serial_list(self, sn_list):
        """Fetch a list of entitlement certificates specified by a list of serial numbers"""
        result = []
        print "sn_list"
        if sn_list:
            sn_list = [str(sn) for sn in sn_list]
            # NOTE: use injected IDENTITY, need to validate this
            # handles disconnected errors properly
            print "sn_list", sn_list
            reply = self.uep.getCertificates(self.identity.getConsumerId(),
                                              serials=sn_list)
            for cert in reply:
                result.append(cert)
        return result

    def _get_expected_serials(self):
        exp = self.get_certificate_serials_list()
        print "exp", exp
        self.report.expected = exp
        return exp

    def delete(self, rogue):
        for cert in rogue:
            try:
                cert.delete()
                self.report.rogue.append(cert)
            except OSError, er:
                log.exception(er)
                log.warn("Failed to delete cert")

        # If we just deleted certs, we need to refresh the now stale
        # entitlement directory before we go to delete expired certs.
        rogue_count = len(self.report.rogue)
        if rogue_count > 0:
            print gettext.ngettext("%s local certificate has been deleted.",
                                   "%s local certificates have been deleted.",
                                   rogue_count) % rogue_count
            self.entdir.refresh()


class EntitlementCertBundlesInstaller(object):
    """Install a list of entitlement cert bundles"""

    def __init__(self, report):
        self.exceptions = []
        self.report = report

    def install(self, cert_bundles):
        """Fetch entitliement certs, install them, and update the report"""
        bundle_installer = EntitlementCertBundleInstaller(self.report)
        for cert_bundle in cert_bundles:
            bundle_installer.install(cert_bundle)
        self.exceptions = bundle_installer.exceptions
        self.post_install()

    # pre and post
    def post_install(self):
        """after all cert bundles have been installed"""
        for installed in self._get_installed():
            print "installed! list", installed

    def get_installed(self):
        return self._get_installed()

    # we have a UpdateReport, use it
    def _get_installed(self):
        return self.report.added


class EntitlementCertBundleInstaller(object):

    def __init__(self, report):
        self.exceptions = []
        self.report = report

    def pre_install(self, bundle):
        print "Ecbi.pre_install", bundle

    def install(self, bundle):
        self.pre_install(bundle)

        cert_bundle_writer = Writer()
        try:
            key, cert = self.build_cert(bundle)
            cert_bundle_writer.write(key, cert)

            self.report.added.append(cert)
        except Exception, e:
            self.install_exception(bundle, e)

        self.post_install(bundle)

    def install_exception(self, bundle, exception):
        log.exception(exception)
        log.error('Bundle not loaded:\n%s\n%s', bundle, exception)

        self.report.exceptions.append(exception)

    def post_install(self, bundle):

        print "Ecbi.post_install"

    # should probably be in python-rhsm/certificate
    def build_cert(self, bundle):
        keypem = bundle['key']
        crtpem = bundle['cert']

        key = Key(keypem)
        cert = create_from_pem(crtpem)

        return (key, cert)


class Disconnected(Exception):
    pass


class ActionReport(object):
    """Base class for cert lib and action reports"""
    name = "Report"

    def __init__(self):
        self._status = None
        self._exceptions = []
        self._updates = []

    def log_entry(self):
        """log report entries"""

        # assuming a useful repr
        log.info(self)

    def format_exceptions(self):
        buf = ''
        for e in self._exceptions:
            buf += ' '.join(str(e).split('-')[1:]).strip()
            buf += '\n'
        return buf

    def print_exceptions(self):
        if self._exceptions:
            print self.format_exceptions()

    def __str__(self):
        template = """%(report_name)s
        status: %(status)s
        updates: %(updates)s
        exceptions: %(exceptions)s
        """
        return template % {'report_name': self.name,
                           'status': self._status,
                           'updates': self._updates,
                           'exceptions': self.format_exceptions()}


class EntCertUpdateReport(ActionReport):
    """Report entitlement cert update action changes"""
    name = "Entitlement Cert Updates"

    def __init__(self):
        self.valid = []
        self.expected = []
        self.added = []
        self.rogue = []
        self._exceptions = []

    def updates(self):
        """total number of ent certs installed and deleted"""
        return (len(self.added) + len(self.rogue))

    # need an ExceptionsReport?
    # FIXME: needs to be properties
    def exceptions(self):
        return self._exceptions

    def write(self, s, title, certificates):
        indent = '  '
        s.append(title)
        if certificates:
            for c in certificates:
                products = c.products
                if not products:
                    s.append('%s[sn:%d (%s) @ %s]' %
                             (indent,
                              c.serial,
                              c.order.name,
                              c.path))
                for product in products:
                    s.append('%s[sn:%d (%s,) @ %s]' %
                             (indent,
                              c.serial,
                              product.name,
                              c.path))
        else:
            s.append('%s<NONE>' % indent)

    def __str__(self):
        s = []
        s.append(_('Total updates: %d') % self.updates())
        s.append(_('Found (local) serial# %s') % self.valid)
        s.append(_('Expected (UEP) serial# %s') % self.expected)
        self.write(s, _('Added (new)'), self.added)
        self.write(s, _('Deleted (rogue):'), self.rogue)
        return '\n'.join(s)


def main():
    print _('Updating entitlement certificates')
    certlib = EntCertLib()
    updates = certlib.update()
    print _('%d updates required') % updates
    print _('done')

if __name__ == '__main__':
    main()
