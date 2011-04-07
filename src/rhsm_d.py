#!/usr/bin/python
#
# Copyright (c) 2010 Red Hat, Inc.
#
# Authors: James Bowes <jbowes@redhat.com>
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

import datetime
import syslog
import gobject
import dbus
import dbus.service
import dbus.glib

from optparse import OptionParser

import sys
sys.path.append("/usr/share/rhsm")
from subscription_manager import managerlib
from subscription_manager import certlib
import rhsm.certificate as certificate

enable_debug = False

RHSM_VALID   = 0
RHSM_EXPIRED = 1
RHSM_WARNING = 2
RHN_CLASSIC  = 3


def debug(msg):
    if enable_debug:
        print msg


def in_warning_period(sorter):

    for entitlement in sorter.valid_entitlement_certs:
        warning_period = datetime.timedelta(
                days=int(entitlement.getOrder().getWarningPeriod()))
        valid_range = entitlement.validRange()
        warning_range = certificate.DateRange(
                valid_range.end() - warning_period, valid_range.end())
        if warning_range.hasNow():
            return True

    return False


def check_status():

    if managerlib.is_registered_with_classic():
        debug("System is already registered with RHN Classic")
        return RHN_CLASSIC

    sorter = certlib.CertSorter(certlib.ProductDirectory(),
            certlib.EntitlementDirectory())

    if len(sorter.unentitled_products.keys()) > 0 or len(sorter.expired_products.keys()) > 0:
        debug("System has one or more certificates that are not valid")
        debug(sorter.unentitled_products.keys())
        debug(sorter.expired_products.keys())
        return RHSM_EXPIRED
    else:
        if in_warning_period(sorter):
            debug("System has one or more entitlements in their warning period")
            return RHSM_WARNING
        else:
            debug("System entitlements appear valid")
            return RHSM_VALID


def check_if_ran_once(checker, loop):
    if checker.has_run:
        debug("dbus has been called once, quitting")
        loop.quit()
    return True


class StatusChecker(dbus.service.Object):

    def __init__(self, bus, keep_alive, loop):
        name = dbus.service.BusName("com.redhat.SubscriptionManager", bus)
        dbus.service.Object.__init__(self, name, "/EntitlementStatus")
        self.has_run = False
        #this will get set after first invocation
        self.last_status = None
        self.keep_alive = keep_alive
        self.loop = loop

    @dbus.service.signal(
        dbus_interface='com.redhat.SubscriptionManager.EntitlementStatus',
        signature='i')
    def entitlement_status_changed(self, status_code):
        debug("signal fired! code is " + str(status_code))

    #this is so we can guarantee exit after the dbus stuff is done, since
    #certain parts of that are async
    def watchdog(self):
        if not self.keep_alive:
            gobject.idle_add(check_if_ran_once, self, self.loop)

    @dbus.service.method(
        dbus_interface="com.redhat.SubscriptionManager.EntitlementStatus",
        out_signature='i')
    def check_status(self):
        """
        returns: 0 if entitlements are valid, 1 if not valid,
                 2 if close to expiry
        """
        ret = check_status()
        if (ret != self.last_status):
            debug("Validity status changed, fire signal")
            #we send the code out, but no one uses it at this time
            self.entitlement_status_changed(ret)
        self.last_status = ret
        self.has_run = True
        self.watchdog()
        return ret


def main():
    parser = OptionParser()
    parser.add_option("-d", "--debug", dest="debug",
            help="Display debug messages", action="store_true", default=False)
    parser.add_option("-k", "--keep-alive", dest="keep_alive",
            help="Stay running (don't shut down after the first dbus call)",
            action="store_true", default=False)
    parser.add_option("-s", "--syslog", dest="syslog",
            help="Run standalone and log result to syslog",
            action="store_true", default=False)

    options, args = parser.parse_args()

    global enable_debug
    enable_debug = options.debug

    # short-circuit dbus initialization
    if options.syslog:
        status = check_status()
        if status == RHSM_EXPIRED:
            syslog.openlog("rhsmd")
            syslog.syslog(syslog.LOG_NOTICE,
                    "This system is missing one or more valid entitlement " +
                    "certificates. " +
                    "Please run subscription-manager-cli for more information.")
        elif status == RHSM_WARNING:
            syslog.openlog("rhsmd")
            syslog.syslog(syslog.LOG_NOTICE,
                    "This system's entitlements are about to expire. " +
                    "Please run subscription-manager-cli for more information.")
        elif status == RHN_CLASSIC:
            syslog.openlog("rhsmd")
            syslog.syslog(syslog.LOG_NOTICE,
                          "This system is registered to RHN Classic")
       
        # Return an exit code for the program. having valid entitlements is
        # good, so it gets an exit status of 0.
        return status

    system_bus = dbus.SystemBus()
    loop = gobject.MainLoop()
    checker = StatusChecker(system_bus, options.keep_alive, loop)

    loop.run()


if __name__ == "__main__":
    main()