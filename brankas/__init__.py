"""Brankas - aplikasi penyimpanan dokumen aman."""
import logging

# Tanpa handler, pesan WARNING akan tercetak ke stderr. Handler berkas dipasang oleh applog.setup_logging().
logging.getLogger("brankas").addHandler(logging.NullHandler())
