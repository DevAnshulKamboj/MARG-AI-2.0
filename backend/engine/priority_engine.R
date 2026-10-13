# backend/engine/priority_engine.R
# Runs the TOPSIS ranking and writes a CSV in the format FastAPI expects.

args <- commandArgs(trailingOnly = TRUE)
output_csv <- args[1]
if (is.na(output_csv)) stop("Usage: Rscript priority_engine.R <output_csv>")
output_csv <- normalizePath(output_csv, mustWork = FALSE)

# Run from this script's own folder so R/ and data/ are found
full_args  <- commandArgs(trailingOnly = FALSE)
script_arg <- full_args[grep("^--file=", full_args)]
setwd(dirname(normalizePath(sub("^--file=", "", script_arg))))

# Optional: rebuild the AHP weights on every run.
# Leave commented out: weights only change when you change a judgment.
# source("01_weights.R")

# Ranking (reads block_requests from PostgreSQL, writes data/ranking_output.csv)
source("02_rank_requests.R")

# Convert to the format FastAPI expects
r <- read.csv("data/ranking_output.csv")

result <- data.frame(
  block_id     = r$request_id,
  topsis_score = r$closeness,
  rank         = r$rank
)

stopifnot(nrow(result) > 0)
stopifnot(!any(duplicated(result$block_id)))

write.csv(result, output_csv, row.names = FALSE)
cat("DONE\n")