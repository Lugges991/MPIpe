# This is a very poor check
# If you want to do better, you can do the following:
# apptainer run docker://bids/validator ~/data/prf/bids_dataset/

from bids import BIDSLayout
layout = BIDSLayout("/home/dramadan/data/prf/bids_dataset/", validate=True, absolute_paths=True)
print(layout.get_subjects()) 

# get bids version
from bids import __version__ as bids_version
print(bids_version)