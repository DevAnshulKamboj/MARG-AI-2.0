"""Settings for the scheduling engine. Change values here, nowhere else."""
from datetime import timedelta

# Clear time kept before and after every train, in every block's stretch.
SAFETY_MARGIN = timedelta(minutes=5)

# A request may start no earlier than its preferred start and at most this much later.
MAX_START_DELAY = timedelta(hours=2)

# Candidate start times are tried every START_STEP, beginning at the preferred start.
START_STEP = timedelta(minutes=5)

# Up   = line from LDH to SRE (chainage increasing)  = line 1
# Down = line from SRE to LDH (chainage decreasing)  = line 2
DIRECTION_TO_LINE = {"UP": 1, "DOWN": 2}
