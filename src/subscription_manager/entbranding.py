

# module for support updating product branding info
# on subscription

# needs to know list of a subscribed entitlement,
# or list of entitlements

# needs to know installed products

#  hmm, we can subscribe before we have a product
#       cert installed? Would we need to check
#       on product cert install as well?


# class BrandFile

# class Brand
#  has a BrandFile

# need map of Brand to Product?

import os


class BrandFile(object):
    brand_path = "/var/lib/rhsm"
    brand_type = "branded_name"

    def __init__(self, filename=None):
        self.filename = filename or os.path.join(self.brand_path, self.brand_type)

    def read(self):
        return "Awesome OS Turbo"

    def write(self, content):
        pass


class Brand(object):
    def __init__(self):
        self.brand_file = BrandFile()


def get_brands(entitlements):
    brands = []
    for entitlement in entitlements:
        print entitlement
