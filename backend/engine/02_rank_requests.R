library(DBI)
source("R/topsis_functions.R")

# --- 1. weights (from AHP) ---------------------------------------------------
wt <- read.csv("data/weights.csv")
w  <- setNames(wt$weight, wt$criterion)
w  <- w[c("Safety", "Urgency", "Operational", "Deadline", "Duration")]

# --- 2. reason scores --------------------------------------------------------
rs <- read.csv("data/reason_scores.csv", strip.white = TRUE)
rs$reason_key <- tolower(gsub("\\s+", " ", trimws(rs$reason)))
stopifnot(!anyDuplicated(rs$reason_key))

# --- 3. requests from the database -------------------------------------------
con <- dbConnect(RPostgres::Postgres(),
                 host = "localhost", port = 5432, dbname = "MARG-AI",
                 user = "postgres", password = Sys.getenv("PGPASSWORD"))
req <- dbGetQuery(con, "
  SELECT block_id                                AS request_id,
         dept                                    AS department,
         block_demanded_for                      AS reason,
         EXTRACT(EPOCH FROM duration) / 3600.0   AS duration_hrs,
         demanded_from::date                     AS requested_date
  FROM   block_requests
")
dbDisconnect(con)
req$reason <- trimws(req$reason)
req$reason_key <- tolower(gsub("\\s+", " ", req$reason))

# --- 4. merge, then build the 5 scores ---------------------------------------
missing <- setdiff(req$reason_key, rs$reason_key)
if (length(missing)) stop("No score row Sfor: ",
                          paste(unique(req$reason[req$reason_key %in% missing]), collapse = " | "))

d <- merge(req, rs[, c("reason_key", "safety", "urgency", "operational")],
           by = "reason_key", all.x = TRUE)

d$days_left <- as.numeric(as.Date(d$requested_date) - Sys.Date())
d$deadline  <- deadline_score(d$days_left)
d$duration  <- duration_score(d$duration_hrs)

# --- 5. TOPSIS ---------------------------------------------------------------
X <- as.matrix(d[, c("safety", "urgency", "operational", "deadline", "duration")])
d$closeness <- topsis_fixed(X, as.numeric(w))
d$rank      <- rank(-d$closeness, ties.method = "min")

out <- d[order(d$rank),
         c("rank", "request_id", "department", "reason", "safety", "urgency",
           "operational", "days_left", "deadline", "duration_hrs", "duration",
           "closeness")]
out$closeness <- round(out$closeness, 4)
print(out, row.names = FALSE)
write.csv(out, "data/ranking_output.csv", row.names = FALSE)