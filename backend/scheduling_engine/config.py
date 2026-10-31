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

# Lines the engine schedules for now. Only the SRE-LDH line (line 2, Down) is switched on.
# Add 1 here to switch the Up line on later (it also needs LDH -> SRE trains in the database).
ENABLED_LINES = {2}

# ---- Step 3: which requests may share one block -------------------------------------------
MAX_REQUESTS_PER_BLOCK = 3

# Two requests may share a block only if the combined stretch is no longer than this (km).
# A request on its own may be longer; the limit applies to blocks that join several requests.
MAX_BLOCK_LENGTH_KM = 15.0

# Department names as typed in the data -> department group (upper-case keys).
DEPARTMENT_GROUPS = {
    "S&T": "S&T",
    "ELEC": "ELEC", "ELECT": "ELEC", "ELECTRICAL": "ELEC",
    "ENGINEERING": "ENG", "CIVIL": "ENG",
}

# Two requests of the same group below may work on overlapping km inside one block.
# Every other pair (different groups, or two ENG requests) must not overlap on km.
# Two ranges that only touch at one km point count as overlapping.
SAME_KM_OK_GROUPS = {"S&T", "ELEC"}

# ---- Step 4: the solver --------------------------------------------------------------------
SCORE_SCALE = 1000                 # priority score (0-1) x this, rounded, gives a whole number
SOLVER_TIME_LIMIT_SECONDS = 30
SOLVER_WORKERS = 8
